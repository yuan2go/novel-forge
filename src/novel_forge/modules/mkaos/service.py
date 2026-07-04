from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path, run_metadata
from novel_forge.modules.os_envelope import enforce_os_envelope, envelope_asset_metadata, envelope_response, is_production_environment
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import (
    BaseAsset,
    KnowledgeCard,
    KnowledgeGraphSnapshot,
    KnowledgeLearningSnapshot,
    KnowledgePack,
    KnowledgePackItem,
    KnowledgeQualityScore,
    KnowledgeUsageBinding,
    KnowledgeUsageEvent,
    RuleCard,
    SourceChunk,
    SourceDocument,
    TemplateCard,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage

MKAOS_FLOWS = {"outline", "chapter_outline", "prose", "review", "revision", "recap", "publish", "feedback"}
KNOWLEDGE_STATUSES = {"extracted", "verified", "flow_bound", "runtime_used", "effective", "needs_review", "deprecated", "quarantined", "do_not_select", "active"}
DO_NOT_SELECT_STATUSES = {"deprecated", "quarantined", "do_not_select"}
QUALITY_DIMENSIONS = {
    "abstraction_score": 0.75,
    "transferability_score": 0.72,
    "actionability_score": 0.72,
    "copyright_risk_score": 0.1,
    "effectiveness_score": 0.5,
    "review_pass_score": 0.5,
    "reader_feedback_score": 0.5,
    "source_reliability_score": 0.7,
    "freshness_score": 0.7,
    "consistency_score": 0.7,
}
RELATION_TYPES = {
    "supports",
    "contradicts",
    "refines",
    "generalizes",
    "specializes",
    "requires",
    "forbids",
    "causes",
    "risks",
    "transforms_into",
    "applies_to_genre",
    "applies_to_platform",
    "validated_by_rule",
    "used_by_template",
    "effect_observed",
}
PACK_ITEM_ROLES = {
    "required",
    "optional",
    "forbidden",
    "constraint",
    "review_rule",
    "canon_context",
    "style_constraint",
    "risk_warning",
}

DEFAULT_RULES: tuple[dict[str, Any], ...] = (
    {
        "rule_name": "反百科化检查",
        "rule_type": "anti_encyclopedia",
        "trigger_condition": "正文出现专业知识、制度解释或世界观说明",
        "check_items": [
            "不存在连续解释性段落",
            "人物没有替作者讲课",
            "知识必须影响当前冲突",
            "可转写成动作、对话、物件或场景",
        ],
        "severity": "high",
        "blocking": False,
        "fix_suggestion": "把解释改成动作、对话、物件或场景变化，并让知识改变人物选择成本。",
        "applicable_flows": ["prose", "review"],
    },
    {
        "rule_name": "因果链检查",
        "rule_type": "logic",
        "trigger_condition": "大纲、细纲、正文或审稿需要验证事件推进",
        "check_items": ["目标、阻碍、行动、结果必须可追溯", "关键结果不能只靠巧合"],
        "severity": "high",
        "blocking": True,
        "fix_suggestion": "补足角色选择和后果之间的因果桥。",
        "applicable_flows": ["outline", "chapter_outline", "review"],
    },
    {
        "rule_name": "人物行为一致性检查",
        "rule_type": "character_consistency",
        "trigger_condition": "人物行为影响情节转折",
        "check_items": ["行动符合目标和压力", "转变有铺垫和代价"],
        "severity": "medium",
        "blocking": False,
        "fix_suggestion": "把行为变化绑定到欲望、伤口、利益或外部压力。",
        "applicable_flows": ["chapter_outline", "prose", "review"],
    },
    {
        "rule_name": "Canon 冲突检查",
        "rule_type": "canon_conflict",
        "trigger_condition": "产物声明事实、人物状态、时间线或设定规则",
        "check_items": ["不得违背项目正典", "critical 冲突必须阻断"],
        "severity": "critical",
        "blocking": True,
        "fix_suggestion": "回滚到冲突前的章节计划或补充正典变更任务。",
        "applicable_flows": ["outline", "chapter_outline", "prose", "review"],
    },
    {
        "rule_name": "知识有效性检查",
        "rule_type": "knowledge_effectiveness",
        "trigger_condition": "知识进入大纲、细纲、正文或审稿",
        "check_items": ["知识不能停留在摘要", "知识必须推动冲突、选择、风险或审稿判断"],
        "severity": "medium",
        "blocking": False,
        "fix_suggestion": "将知识转为利益冲突、场景约束或审稿规则。",
        "applicable_flows": ["outline", "chapter_outline", "prose", "review"],
    },
    {
        "rule_name": "章节钩子检查",
        "rule_type": "chapter_hook",
        "trigger_condition": "章节计划或正文收束处",
        "check_items": ["章节末尾改变下一章目标", "钩子不是纯信息悬念"],
        "severity": "medium",
        "blocking": False,
        "fix_suggestion": "让钩子变成新的义务、风险、代价或关系压力。",
        "applicable_flows": ["chapter_outline", "prose", "review"],
    },
    {
        "rule_name": "制度知识是否推动人物利益冲突",
        "rule_type": "institutional_effectiveness",
        "trigger_condition": "制度、历史、行业或专业知识被用于生产",
        "check_items": ["至少一方获利", "至少一方受损", "主角被迫行动或承担风险"],
        "severity": "high",
        "blocking": False,
        "fix_suggestion": "把制度知识落到田契、税源、豪强、佃户或县衙行动上。",
        "applicable_flows": ["outline", "chapter_outline", "prose", "review"],
    },
    {
        "rule_name": "人物利益冲突检查",
        "rule_type": "interest_conflict",
        "trigger_condition": "知识被用于结构或场景",
        "check_items": ["反派有经济或权力动机", "主角利益被直接影响", "冲突结果改变资源分配"],
        "severity": "high",
        "blocking": False,
        "fix_suggestion": "明确谁得到资源、谁失去资源、谁必须冒险。",
        "applicable_flows": ["outline", "chapter_outline", "review"],
    },
)


def import_source_document(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    storage.ensure_layout()
    text = str(payload.get("text") or payload.get("content") or "").strip()
    if not text:
        raise ValueError("source text must not be empty")
    title = str(payload.get("title") or payload.get("name") or "MKAOS source").strip()
    source_kind = str(payload.get("source_kind") or payload.get("kind") or "manual_note").strip()
    source_uri = str(payload.get("source_uri") or payload.get("source") or title).strip()
    project_id = str(payload.get("project_id") or "local-system").strip()
    workspace_path = str(payload.get("workspace_path") or "").strip()
    os_envelope = _mkaos_envelope(storage, payload, operation="mkaos.source_import", asset_type="source_document", project_id=project_id, task_type="source_import")
    rights = payload.get("rights") if isinstance(payload.get("rights"), dict) else {}
    rights = {
        "authorization": str(rights.get("authorization") or payload.get("rights_authorization") or "unknown"),
        "copyright_boundary": str(rights.get("copyright_boundary") or payload.get("copyright_boundary") or "MKAOS source stored for abstract knowledge extraction"),
        "allow_downstream_generation": bool(rights.get("allow_downstream_generation", False)),
    }
    content_hash = _hash_text(text)
    asset = SourceDocument(
        title=title,
        source=source_uri,
        tags=_dedupe(["mkaos", "source", source_kind, *[str(tag) for tag in payload.get("tags") or []]]),
        content={
            "text": text,
            "source_kind": source_kind,
            "source_uri": source_uri,
            "content_hash": content_hash,
            "clean_status": "pending",
            "chunk_count": 0,
            "mkaos_source": True,
        },
        metadata={
            "project_id": project_id,
            "workspace_path": workspace_path,
            "rights": rights,
            "mkaos": True,
            "use_in_generation_rag": False,
            "source_kind": source_kind,
            "content_hash": content_hash,
            "run_metadata": run_metadata("mkaos.import_source", SourceDocument(title=title, source=source_uri, content={"text": text[:200]})),
            **envelope_asset_metadata(os_envelope),
        },
    )
    _ensure_valid(asset.to_dict())
    path = storage.write_asset("raw", asset)
    chunks = rebuild_source_chunks(storage, asset.id)
    source = storage.read_json(path)
    return {"path": _display_path(storage.root, path), "asset": source, "chunks": chunks["chunks"], "chunk_count": chunks["chunk_count"]}


def rebuild_source_chunks(storage: LocalStorage, source_ref: str | Path) -> dict[str, Any]:
    source_path, source = _find_asset(storage, source_ref, asset_type="source_document", categories=["raw"])
    content = source.get("content", {}) if isinstance(source.get("content", {}), dict) else {}
    raw_text = str(content.get("text") or "")
    cleaned = clean_source_text(raw_text)
    chunk_texts = split_clean_text(cleaned)
    written: list[dict[str, Any]] = []
    project_id = str(source.get("metadata", {}).get("project_id") or "local-system")
    workspace_path = str(source.get("metadata", {}).get("workspace_path") or "")
    source_envelope_meta = envelope_asset_metadata(source.get("metadata", {}).get("os_envelope") if isinstance(source.get("metadata", {}), dict) else {})
    source_rel = _display_path(storage.root, source_path)
    for index, chunk_text in enumerate(chunk_texts):
        content_hash = _hash_text(chunk_text)
        existing = _find_existing_source_chunk(storage, str(source.get("id", "")), content_hash)
        if existing:
            written.append(existing)
            continue
        asset = SourceChunk(
            title=f"{source.get('title') or source.get('id')} chunk {index + 1}",
            source=str(source.get("id", "")),
            tags=["mkaos", "source-chunk", f"chunk-{index + 1}"],
            content={
                "source_document_id": source.get("id", ""),
                "source_document_path": source_rel,
                "chunk_index": index,
                "raw_text": chunk_text,
                "clean_text": chunk_text,
                "content_hash": content_hash,
                "clean_status": "cleaned",
            },
            metadata={
                "project_id": project_id,
                "workspace_path": workspace_path,
                "mkaos": True,
                "use_in_generation_rag": False,
                "content_hash": content_hash,
                "source_asset_path": source_rel,
                "evidence_layer_only": True,
                **source_envelope_meta,
            },
            references=[str(source.get("id", "")), source_rel],
        )
        _ensure_valid(asset.to_dict())
        path = storage.write_asset("raw", asset)
        written.append(_asset_row(storage, path, storage.read_json(path)))
    source["content"] = {
        **content,
        "clean_status": "cleaned",
        "cleaned_text": cleaned,
        "chunk_count": len(written),
        "last_cleaned_at": utc_now(),
    }
    source["updated_at"] = utc_now()
    storage.write_json(source_path, source)
    return {
        "source_path": source_rel,
        "source_id": source.get("id", ""),
        "chunk_count": len(written),
        "chunks": written,
        "cleaning": {"status": "cleaned", "deduped": True, "raw_source_boundary": "evidence_layer_only"},
    }


def clean_source_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in str(text or "").splitlines()]
    lines = [line for line in lines if line]
    frequency: dict[str, int] = {}
    for line in lines:
        if len(line) <= 40:
            frequency[line] = frequency.get(line, 0) + 1
    paragraphs: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if frequency.get(line, 0) >= 3:
            continue
        normalized = re.sub(r"^\s*(第?\d+\s*/\s*\d+|page\s+\d+)\s*$", "", line, flags=re.IGNORECASE).strip()
        if not normalized:
            continue
        key = _hash_text(normalized)
        if key in seen:
            continue
        seen.add(key)
        paragraphs.append(normalized)
    return "\n\n".join(paragraphs)


def split_clean_text(text: str, *, target_chars: int = 600) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", str(text or "")) if part.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in paragraphs:
        if current and current_len + len(paragraph) > target_chars:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(paragraph)
        current_len += len(paragraph)
    if current:
        chunks.append("\n\n".join(current))
    return chunks or ([str(text).strip()] if str(text).strip() else [])


def list_source_documents(storage: LocalStorage, *, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    return _list_assets(storage, "raw", "source_document", project_id=project_id, mkaos_only=True, limit=limit)


def list_source_chunks(storage: LocalStorage, source_ref: str | Path | None = None, *, project_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    source_id = ""
    if source_ref:
        _, source = _find_asset(storage, source_ref, asset_type="source_document", categories=["raw"])
        source_id = str(source.get("id", ""))
    rows = _list_assets(storage, "raw", "source_chunk", project_id=project_id, mkaos_only=True, limit=limit)
    if source_id:
        rows = [row for row in rows if str(row.get("content", {}).get("source_document_id", "")) == source_id]
    return sorted(rows, key=lambda row: int(row.get("content", {}).get("chunk_index", 0) or 0))


def create_knowledge_card(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    concept_name = str(payload.get("concept_name") or payload.get("title") or "").strip()
    if not concept_name:
        raise ValueError("concept_name must not be empty")
    source_chunk_ids = [str(item) for item in payload.get("source_chunk_ids") or [] if str(item).strip()]
    core = str(payload.get("core_explanation") or payload.get("explanation") or "abstract reusable knowledge principle").strip()
    project_id = str(payload.get("project_id") or "local-system").strip()
    workspace_path = str(payload.get("workspace_path") or "").strip()
    os_envelope = _mkaos_envelope(storage, payload, operation="mkaos.knowledge_create", asset_type="knowledge_card", project_id=project_id, task_type="knowledge_create")
    status = _normalize_knowledge_status(str(payload.get("status") or "verified").strip())
    risk_level = str(payload.get("risk_level") or "low").strip()
    quality_dimensions = _quality_dimensions(payload)
    overall_quality = _float(payload.get("overall_quality_score"), _overall_quality_score(quality_dimensions))
    evidence_span_refs = _strings(payload.get("evidence_span_refs"))
    content = {
        "concept_name": concept_name,
        "concept_aliases": _strings(payload.get("concept_aliases")),
        "discipline": str(payload.get("discipline") or "general").strip(),
        "sub_discipline": str(payload.get("sub_discipline") or "").strip(),
        "knowledge_type": str(payload.get("knowledge_type") or "mechanism").strip(),
        "core_explanation": core,
        "principles": _strings(payload.get("principles")) or [core],
        "source_chunk_ids": source_chunk_ids,
        "evidence_span_refs": evidence_span_refs,
        "confidence": _float(payload.get("confidence"), 0.7),
        "source_reliability": _float(payload.get("source_reliability"), 0.7),
        "applicable_genres": _strings(payload.get("applicable_genres")),
        "applicable_platforms": _strings(payload.get("applicable_platforms")),
        "platform_weights": payload.get("platform_weights") if isinstance(payload.get("platform_weights"), dict) else {},
        "genre_weights": payload.get("genre_weights") if isinstance(payload.get("genre_weights"), dict) else {},
        "risk_level": risk_level,
        "risk_notes": str(payload.get("risk_notes") or "").strip(),
        "status": status,
        "quality_dimensions": quality_dimensions,
        "quality_score": _float(payload.get("quality_score"), overall_quality),
        "overall_quality_score": overall_quality,
        "weight": _float(payload.get("weight"), 1.0),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    }
    asset = KnowledgeCard(
        title=concept_name,
        source=str(payload.get("source") or (source_chunk_ids[0] if source_chunk_ids else "mkaos-manual")),
        tags=_dedupe(["mkaos", "knowledge-card", content["discipline"], content["knowledge_type"], *[str(tag) for tag in payload.get("tags") or []]]),
        content=content,
        metadata={
            "project_id": project_id,
            "workspace_path": workspace_path,
            "mkaos": True,
            "asset_status": status,
            "risk_level": risk_level,
            "quality_score": content["quality_score"],
            "overall_quality_score": content["overall_quality_score"],
            "quality_dimensions": quality_dimensions,
            "weight": content["weight"],
            "source_chunk_ids": source_chunk_ids,
            "evidence_span_refs": evidence_span_refs,
            "copyright_boundary": "abstract structure knowledge card derived from source evidence; no raw source expression for prose",
            "run_metadata": run_metadata("mkaos.create_knowledge_card", KnowledgeCard(title=concept_name, content={"principles": [core]})),
            **envelope_asset_metadata(os_envelope),
        },
        references=filter_project_safe_references(storage, project_id, _dedupe([*source_chunk_ids, *evidence_span_refs])),
    )
    _ensure_valid(asset.to_dict())
    path = storage.write_asset("knowledge", asset)
    record_mkaos_mutation(storage, asset_type="knowledge_card", asset_id=asset.id, mutation_type="create", new_payload=asset.to_dict(), reason="create_knowledge_card", actor=str(payload.get("actor") or "mkaos"), trace_id=str(os_envelope.get("trace_id") or ""))
    record_knowledge_version(storage, asset.to_dict(), previous_payload={}, reason="create", actor=str(payload.get("actor") or "mkaos"), trace_id=str(os_envelope.get("trace_id") or ""))
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path), "validation": {"ok": True, "errors": []}}


def update_knowledge_card(storage: LocalStorage, knowledge_ref: str | Path, patch: dict[str, Any]) -> dict[str, Any]:
    path, data = _find_asset(storage, knowledge_ref, asset_type="knowledge_card", categories=["knowledge"])
    previous = json.loads(json.dumps(data, ensure_ascii=False))
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    project_id = str(patch.get("project_id") or metadata.get("project_id") or "local-system")
    os_envelope = _mkaos_envelope(storage, patch, operation="mkaos.knowledge_update", asset_type="knowledge_card", project_id=project_id, task_type="knowledge_update")
    for key, value in patch.items():
        if key in {"metadata", "content"}:
            continue
        if key == "status":
            value = _normalize_knowledge_status(str(value))
        if key == "quality_dimensions" and isinstance(value, dict):
            value = _quality_dimensions(value)
            content["overall_quality_score"] = _overall_quality_score(value)
            content["quality_score"] = content["overall_quality_score"]
        if key in {"status", "risk_level", "quality_score", "weight"}:
            metadata["asset_status" if key == "status" else key] = value
        content[key] = value
    if isinstance(patch.get("metadata"), dict):
        metadata.update(patch["metadata"])
    if isinstance(patch.get("content"), dict):
        content.update(patch["content"])
    metadata.update(envelope_asset_metadata(os_envelope))
    data["content"] = content
    data["metadata"] = metadata
    data["updated_at"] = utc_now()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(path, data)
    updated = storage.read_json(path)
    trace_id = str(os_envelope.get("trace_id") or patch.get("trace_id") or "")
    record_mkaos_mutation(storage, asset_type="knowledge_card", asset_id=str(updated.get("id") or ""), mutation_type="update", previous_payload=previous, new_payload=updated, changed_fields=_changed_fields(previous, updated), reason=str(patch.get("reason") or "update_knowledge_card"), actor=str(patch.get("actor") or "mkaos"), trace_id=trace_id)
    record_knowledge_version(storage, updated, previous_payload=previous, reason=str(patch.get("reason") or "update"), actor=str(patch.get("actor") or "mkaos"), trace_id=trace_id)
    if _knowledge_status(updated) in {"deprecated", "quarantined"}:
        analyze_knowledge_impact(storage, str(updated.get("id") or ""), change_type=_knowledge_status(updated), dry_run=False)
    return {"path": _display_path(storage.root, path), "asset": updated, "validation": {"ok": True, "errors": []}}


def list_knowledge_cards(storage: LocalStorage, *, project_id: str | None = None, include_deprecated: bool = True, limit: int = 200) -> list[dict[str, Any]]:
    rows = _list_assets(storage, "knowledge", "knowledge_card", project_id=project_id, mkaos_only=False, limit=limit)
    if not include_deprecated:
        rows = [row for row in rows if _knowledge_status(row["asset"]) != "deprecated"]
    return rows


def create_usage_binding(storage: LocalStorage, knowledge_ref: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    _, knowledge = _find_asset(storage, knowledge_ref, asset_type="knowledge_card", categories=["knowledge"])
    flow = _valid_flow(str(payload.get("flow") or ""))
    project_id = str(knowledge.get("metadata", {}).get("project_id") or "local-system")
    os_envelope = _mkaos_envelope(storage, payload, operation="mkaos.usage_binding_create", asset_type="knowledge_usage_binding", project_id=project_id, task_type=flow)
    content = {
        "knowledge_id": str(knowledge.get("id", "")),
        "flow": flow,
        "usage_type": str(payload.get("usage_type") or _default_usage_type(flow)).strip(),
        "usage_granularity": str(payload.get("usage_granularity") or ("chapter" if flow in {"chapter_outline", "prose"} else "project")).strip(),
        "input_role": str(payload.get("input_role") or _default_input_role(flow)).strip(),
        "output_form": str(payload.get("output_form") or _default_output_form(flow)).strip(),
        "prompt_fragment": str(payload.get("prompt_fragment") or "").strip(),
        "constraint_text": str(payload.get("constraint_text") or "").strip(),
        "review_rule_id": str(payload.get("review_rule_id") or "").strip(),
        "template_id": str(payload.get("template_id") or "").strip(),
        "priority": int(payload.get("priority", 100) or 100),
        "risk_level": str(payload.get("risk_level") or knowledge.get("metadata", {}).get("risk_level") or "low").strip(),
        "enabled": bool(payload.get("enabled", True)),
    }
    asset = KnowledgeUsageBinding(
        title=f"{knowledge.get('title') or knowledge.get('id')} -> {flow}",
        source=str(knowledge.get("id", "")),
        tags=["mkaos", "usage-binding", flow, content["usage_type"]],
        content=content,
        metadata={
            "project_id": str(knowledge.get("metadata", {}).get("project_id") or "local-system"),
            "workspace_path": str(knowledge.get("metadata", {}).get("workspace_path") or ""),
            "mkaos": True,
            "use_in_generation_rag": False,
            "enabled": content["enabled"],
            "risk_level": content["risk_level"],
            "run_metadata": run_metadata("mkaos.create_usage_binding", KnowledgeUsageBinding(title=f"{knowledge.get('id')} {flow}", content=content)),
            **envelope_asset_metadata(os_envelope),
        },
        references=_dedupe([str(knowledge.get("id", "")), content["review_rule_id"], content["template_id"]]),
    )
    _ensure_valid(asset.to_dict())
    path = storage.write_asset("knowledge", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path), "validation": {"ok": True, "errors": []}}


def update_usage_binding(storage: LocalStorage, binding_ref: str | Path, patch: dict[str, Any]) -> dict[str, Any]:
    path, data = _find_asset(storage, binding_ref, asset_type="knowledge_usage_binding", categories=["knowledge"])
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    project_id = str(patch.get("project_id") or metadata.get("project_id") or "local-system")
    os_envelope = _mkaos_envelope(storage, patch, operation="mkaos.usage_binding_update", asset_type="knowledge_usage_binding", project_id=project_id, task_type=str(patch.get("flow") or content.get("flow") or "usage_binding"))
    for key, value in patch.items():
        if key == "flow":
            value = _valid_flow(str(value))
        content[key] = value
    data["content"] = content
    data["metadata"] = {**metadata, **envelope_asset_metadata(os_envelope)}
    data["updated_at"] = utc_now()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    storage.write_json(path, data)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path), "validation": {"ok": True, "errors": []}}


def list_usage_bindings(storage: LocalStorage, knowledge_ref: str | Path | None = None, *, flow: str | None = None, enabled: bool | None = None, limit: int = 300) -> list[dict[str, Any]]:
    knowledge_id = ""
    if knowledge_ref:
        _, knowledge = _find_asset(storage, knowledge_ref, asset_type="knowledge_card", categories=["knowledge"])
        knowledge_id = str(knowledge.get("id", ""))
    rows = _list_assets(storage, "knowledge", "knowledge_usage_binding", limit=limit)
    if knowledge_id:
        rows = [row for row in rows if str(row.get("content", {}).get("knowledge_id", "")) == knowledge_id]
    if flow:
        rows = [row for row in rows if str(row.get("content", {}).get("flow", "")) == flow]
    if enabled is not None:
        rows = [row for row in rows if bool(row.get("content", {}).get("enabled", False)) is enabled]
    return rows


def ensure_default_rule_cards(storage: LocalStorage) -> list[dict[str, Any]]:
    rows = list_rule_cards(storage, limit=500)
    existing_names = {str(row.get("content", {}).get("rule_name", "")) for row in rows}
    created: list[dict[str, Any]] = []
    for rule in DEFAULT_RULES:
        if str(rule["rule_name"]) in existing_names:
            continue
        created.append(create_rule_card(storage, rule)["asset"])
    return list_rule_cards(storage, limit=500) if created else rows


def create_rule_card(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    rule_name = str(payload.get("rule_name") or payload.get("title") or "").strip()
    if not rule_name:
        raise ValueError("rule_name must not be empty")
    applicable_flows = [_valid_flow(item) for item in _strings(payload.get("applicable_flows"))] or ["review"]
    project_id = str(payload.get("project_id") or "local-system")
    os_envelope = _mkaos_envelope(storage, payload, operation="mkaos.rule_create", asset_type="rule_card", project_id=project_id, task_type="rule_create")
    content = {
        "rule_name": rule_name,
        "rule_type": str(payload.get("rule_type") or "review").strip(),
        "trigger_condition": str(payload.get("trigger_condition") or "").strip(),
        "check_items": _strings(payload.get("check_items")),
        "severity": str(payload.get("severity") or "medium").strip(),
        "blocking": bool(payload.get("blocking", False)),
        "fix_suggestion": str(payload.get("fix_suggestion") or "").strip(),
        "applicable_flows": applicable_flows,
        "applicable_genres": _strings(payload.get("applicable_genres")),
        "enabled": bool(payload.get("enabled", True)),
    }
    asset = RuleCard(
        title=rule_name,
        source=str(payload.get("source") or "mkaos-rule-library"),
        tags=["mkaos", "rule-card", content["rule_type"], content["severity"]],
        content=content,
        metadata={
            "project_id": project_id,
            "workspace_path": str(payload.get("workspace_path") or ""),
            "mkaos": True,
            "use_in_generation_rag": False,
            "risk_level": content["severity"],
            "run_metadata": run_metadata("mkaos.create_rule_card", RuleCard(title=rule_name, content=content)),
            **envelope_asset_metadata(os_envelope),
        },
    )
    _ensure_valid(asset.to_dict())
    path = storage.write_asset("quality_standards", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path), "validation": {"ok": True, "errors": []}}


def list_rule_cards(storage: LocalStorage, *, flow: str | None = None, enabled: bool | None = None, limit: int = 200) -> list[dict[str, Any]]:
    rows = _list_assets(storage, "quality_standards", "rule_card", limit=limit)
    if flow:
        rows = [row for row in rows if flow in row.get("content", {}).get("applicable_flows", [])]
    if enabled is not None:
        rows = [row for row in rows if bool(row.get("content", {}).get("enabled", False)) is enabled]
    return rows


def create_template_card(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    template_name = str(payload.get("template_name") or payload.get("title") or "").strip()
    if not template_name:
        raise ValueError("template_name must not be empty")
    applicable_flows = [_valid_flow(item) for item in _strings(payload.get("applicable_flows"))] if payload.get("applicable_flows") else ["outline", "chapter_outline"]
    project_id = str(payload.get("project_id") or "local-system")
    os_envelope = _mkaos_envelope(storage, payload, operation="mkaos.template_create", asset_type="template_card", project_id=project_id, task_type="template_create")
    content = {
        "template_name": template_name,
        "template_type": str(payload.get("template_type") or "story_mechanism").strip(),
        "structure": payload.get("structure") if payload.get("structure") else ["pressure", "choice", "cost", "payoff", "next hook"],
        "usage_constraints": _strings(payload.get("usage_constraints")) or ["adapt to project canon", "do not copy protected expression"],
        "anti_copy_rules": _strings(payload.get("anti_copy_rules")) or ["no source-specific names", "no copied scene sequence"],
        "applicable_flows": applicable_flows,
        "enabled": bool(payload.get("enabled", True)),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    }
    asset = TemplateCard(
        title=template_name,
        source=str(payload.get("source") or "mkaos-template-library"),
        tags=["mkaos", "template-card", content["template_type"]],
        content=content,
        metadata={
            "project_id": project_id,
            "workspace_path": str(payload.get("workspace_path") or ""),
            "mkaos": True,
            "use_in_generation_rag": False,
            "copyright_boundary": "abstract reusable template only; no protected expression",
            "run_metadata": run_metadata("mkaos.create_template_card", TemplateCard(title=template_name, content=content)),
            **envelope_asset_metadata(os_envelope),
        },
    )
    _ensure_valid(asset.to_dict())
    path = storage.write_asset("templates", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path), "validation": {"ok": True, "errors": []}}


def list_template_cards(storage: LocalStorage, *, flow: str | None = None, enabled: bool | None = None, limit: int = 200) -> list[dict[str, Any]]:
    rows = _list_assets(storage, "templates", "template_card", limit=limit)
    if flow:
        rows = [row for row in rows if flow in row.get("content", {}).get("applicable_flows", [])]
    if enabled is not None:
        rows = [row for row in rows if bool(row.get("content", {}).get("enabled", False)) is enabled]
    return rows


def build_knowledge_pack(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    flow = _valid_flow(str(payload.get("flow") or ""))
    ensure_default_rule_cards(storage)
    project_id = str(payload.get("project_id") or "local-system").strip()
    workspace_path = str(payload.get("workspace_path") or "").strip()
    genre = str(payload.get("genre") or "").strip()
    platform = str(payload.get("platform") or "").strip()
    chapter_id = str(payload.get("chapter_id") or payload.get("chapter") or "").strip()
    task_id = str(payload.get("task_id") or f"{flow}-{project_id}-{chapter_id or 'project'}")
    current_goal = str(payload.get("current_goal") or payload.get("goal") or "").strip()
    budget = _knowledge_budget(flow, payload.get("knowledge_budget"))
    os_envelope = _mkaos_envelope(
        storage,
        payload,
        operation="mkaos.pack_build",
        asset_type="knowledge_pack",
        project_id=project_id,
        task_type=flow,
        token_budget=budget,
    )
    selector_policy = _selector_policy(payload, os_envelope, budget)
    bindings = list_usage_bindings(storage, flow=flow, enabled=True, limit=500)
    knowledge_items: list[dict[str, Any]] = []
    selector_rejections: list[dict[str, Any]] = []
    for binding in bindings:
        item = _pack_item_from_binding(storage, binding, flow, genre=genre, platform=platform, project_id=project_id, selector_policy=selector_policy)
        if item and item.get("selector_decision", {}).get("selected", True):
            knowledge_items.append(item)
        elif item:
            selector_rejections.append({
                "knowledge_id": item.get("knowledge_id", ""),
                "binding_id": item.get("binding_id", ""),
                "concept_name": item.get("concept_name", ""),
                "reason": item.get("selector_decision", {}).get("reason", "selector_rejected"),
                "risk_level": item.get("risk_level", ""),
            })
    candidate_items = list(knowledge_items)
    knowledge_items = _select_pack_items(knowledge_items, flow=flow, budget=budget)
    selected_ids = {str(item.get("knowledge_id") or "") for item in knowledge_items}
    for item in candidate_items:
        if str(item.get("knowledge_id") or "") not in selected_ids:
            selector_rejections.append(
                {
                    "knowledge_id": item.get("knowledge_id", ""),
                    "binding_id": item.get("binding_id", ""),
                    "concept_name": item.get("concept_name", ""),
                    "reason": "over_budget",
                    "risk_level": item.get("risk_level", ""),
                    "score_breakdown": item.get("selector_decision", {}),
                }
            )
    if flow == "prose":
        required_items = [item for item in knowledge_items if item.get("item_role") == "required"]
        optional_items = [item for item in knowledge_items if item.get("item_role") == "optional"]
        knowledge_items = [*required_items, *optional_items[: max(0, budget["max_core_knowledge"] - len(required_items))], *[item for item in knowledge_items if item.get("item_role") not in {"required", "optional"}]]
    grouped = _group_pack_items(knowledge_items)
    rule_rows = [
        _rule_payload(row)
        for row in list_rule_cards(storage, flow=flow, enabled=True, limit=200)
        if _genre_matches(row.get("content", {}).get("applicable_genres", []), genre)
    ]
    if flow != "review":
        rule_rows = rule_rows[:8]
    canon_context = _canon_context(storage, project_id)
    constraints = _generation_constraints(flow, knowledge_items, rule_rows)
    style_constraints = _style_constraints(flow, knowledge_items)
    risk_warnings = _risk_warnings(knowledge_items)
    output_contract = _output_contract(flow)
    selector_decision = _persist_selector_decision(
        storage,
        project_id=project_id,
        flow=flow,
        selected_items=knowledge_items,
        rejected_items=selector_rejections,
        selector_policy=selector_policy,
        budget=budget,
        payload=payload,
        envelope=os_envelope,
    )
    conflicts = detect_knowledge_conflicts(
        storage,
        {
            "project_id": project_id,
            "flow": flow,
            "platform": platform,
            "task_goal": current_goal,
            "knowledge_items": knowledge_items,
            "source_policy": selector_policy.get("source_policy", {}),
        },
    )
    if is_production_environment(str(os_envelope.get("environment") or payload.get("environment") or "")) and conflicts["blocking_count"] > 0:
        raise ValueError("MKAOS blocking knowledge conflict: " + "; ".join(item["explanation"] for item in conflicts["conflicts"] if item.get("blocking")))
    fusion_path = create_cross_discipline_fusion_path(
        storage,
        {
            "project_id": project_id,
            "flow": flow,
            "task_goal": current_goal,
            "genre": genre,
            "platform": platform,
            "selected_knowledge_ids": [str(item.get("knowledge_id") or "") for item in knowledge_items],
            "persist": True,
        },
    ) if len({str(item.get("discipline") or "") for item in knowledge_items if str(item.get("discipline") or "")}) >= 2 else {}
    content = {
        "knowledge_pack_id": "",
        "task_id": task_id,
        "project_id": project_id,
        "workspace_path": workspace_path,
        "flow": flow,
        "genre": genre,
        "platform": platform,
        "chapter_id": chapter_id,
        "current_goal": current_goal,
        "required_knowledge": grouped["required"],
        "optional_knowledge": grouped["optional"],
        "forbidden_knowledge": grouped["forbidden"],
        "canon_context": canon_context,
        "generation_constraints": constraints,
        "review_rules": rule_rows,
        "style_constraints": style_constraints,
        "knowledge_budget": budget,
        "selector_policy": selector_policy,
        "selector_decision_id": selector_decision["asset"]["id"],
        "selector_decision_path": selector_decision["path"],
        "selector_rejections": selector_rejections,
        "knowledge_conflicts": conflicts["conflicts"],
        "blocking_conflict_count": conflicts["blocking_count"],
        "cross_discipline_fusion_path": fusion_path.get("path", ""),
        "risk_warnings": risk_warnings,
        "output_contract": output_contract,
        "pack_items": knowledge_items,
        "source_isolation": {"prose_raw_source_text_included": False, "source_chunk_ids_only": True},
        "warnings": [] if knowledge_items else ["no enabled matching knowledge_usage_binding found"],
    }
    pack_id = _stable_asset_id("knowledge_pack", project_id, flow, task_id, chapter_id)
    content["knowledge_pack_id"] = pack_id
    asset = KnowledgePack(
        id=pack_id,
        title=f"MKAOS {flow} pack {task_id}",
        source=task_id,
        tags=["mkaos", "knowledge-pack", flow],
        content=content,
        metadata={
            "project_id": project_id,
            "workspace_path": workspace_path,
            "mkaos": True,
            "use_in_generation_rag": False,
            "flow": flow,
            "task_id": task_id,
            "chapter_id": chapter_id,
            "selector_decision_id": selector_decision["asset"]["id"],
            "source_isolation": "no_source_chunk_raw_text_in_prose_pack",
            "run_metadata": run_metadata("mkaos.build_knowledge_pack", KnowledgePack(title=f"{flow} pack", content=content)),
            **envelope_asset_metadata(os_envelope),
        },
        references=filter_project_safe_references(storage, project_id, _dedupe([item.get("knowledge_id", "") for item in knowledge_items])),
    )
    _ensure_valid(asset.to_dict())
    path = storage.write_asset("contexts", asset)
    item_paths = _write_pack_item_assets(storage, asset, knowledge_items)
    data = storage.read_json(path)
    data["content"]["knowledge_pack_item_paths"] = item_paths
    storage.write_json(path, data)
    record_mkaos_mutation(storage, asset_type="knowledge_pack", asset_id=pack_id, mutation_type="create", new_payload=data, reason="build_knowledge_pack", actor=str(payload.get("actor") or "mkaos"), trace_id=str(os_envelope.get("trace_id") or ""))
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path), "validation": {"ok": True, "errors": []}}


def get_knowledge_pack(storage: LocalStorage, pack_ref: str | Path) -> dict[str, Any]:
    path, data = _find_asset(storage, pack_ref, asset_type="knowledge_pack", categories=["contexts"])
    return {"path": _display_path(storage.root, path), "asset": data}


def pack_prompt_preview(storage: LocalStorage, pack_ref: str | Path) -> dict[str, Any]:
    pack = get_knowledge_pack(storage, pack_ref)
    content = pack["asset"].get("content", {})
    lines = [
        f"# MKAOS Knowledge Pack: {content.get('flow')}",
        f"Task: {content.get('task_id')}",
        f"Goal: {content.get('current_goal') or '-'}",
        "Required:",
        *[f"- {item.get('concept_name')}: {item.get('constraint_text') or item.get('core_explanation')}" for item in content.get("required_knowledge", [])[:8]],
        "Optional:",
        *[f"- {item.get('concept_name')}: {item.get('output_form')}" for item in content.get("optional_knowledge", [])[:8]],
        "Constraints:",
        *[f"- {item}" for item in content.get("generation_constraints", [])[:12]],
        "Review Rules:",
        *[f"- {item.get('rule_name')} ({item.get('severity')})" for item in content.get("review_rules", [])[:12]],
    ]
    preview = "\n".join(lines)
    if content.get("flow") == "prose" and "raw_text" in preview:
        raise ValueError("prose prompt preview must not contain source chunk raw_text")
    return {"pack_path": pack["path"], "preview": preview, "source_isolation": content.get("source_isolation", {})}


def adapt_pack_for_flow(storage: LocalStorage, pack_ref: str | Path, flow: str | None = None) -> dict[str, Any]:
    pack = get_knowledge_pack(storage, pack_ref)
    content = pack["asset"].get("content", {}) if isinstance(pack["asset"].get("content", {}), dict) else {}
    resolved_flow = _valid_flow(flow or str(content.get("flow") or ""))
    if resolved_flow == "outline":
        return _outline_adapter(content)
    if resolved_flow == "chapter_outline":
        return _chapter_outline_adapter(content)
    if resolved_flow == "prose":
        return _prose_adapter(content)
    return _review_adapter(content)


def validate_artifact(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    checks = set(_strings(payload.get("checks")) or ["canon", "logic", "anti_encyclopedia", "knowledge_usage", "platform"])
    text = _artifact_text(storage, payload)
    issues: list[dict[str, Any]] = []
    if "anti_encyclopedia" in checks:
        issues.extend(_anti_encyclopedia_issues(storage, text))
    if "canon" in checks:
        canon = validate_canon_conflict(storage, payload)
        issues.extend(canon["issues"])
    if "knowledge_usage" in checks:
        issues.extend(_knowledge_usage_issues(storage, payload))
    if "logic" in checks and text and _looks_like_broken_causality(text):
        issues.append(_issue("rule_causal_chain", "因果链检查", "medium", False, "出现结果但缺少可见行动或代价。", "补足目标、阻碍、行动、结果。", "scene"))
    if "platform" in checks and len(text) > 0 and len(text) < 30:
        issues.append(_issue("rule_platform_minimum", "平台风险检查", "low", False, "文本过短，无法判断平台节奏。", "补充完整章节或片段。", "artifact"))
    score = max(0, 100 - sum(_severity_penalty(issue.get("severity", "")) for issue in issues))
    passed = not any(issue.get("blocking") or issue.get("severity") in {"critical", "high"} for issue in issues)
    return {
        "passed": passed,
        "score": score,
        "issues": issues,
        "usage_assessment": {
            "knowledge_usage_checked": "knowledge_usage" in checks,
            "anti_encyclopedia_hit": any(issue.get("rule_name") == "反百科化检查" for issue in issues),
            "canon_conflict_hit": any(issue.get("rule_name") == "Canon 冲突检查" for issue in issues),
        },
    }


def validate_canon_conflict(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    return check_canon_conflict(storage, payload)


def check_canon_conflict(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    check_input = _canon_conflict_check_input(storage, payload)
    text = str(check_input.get("artifact_text") or "")
    canon = check_input.get("canon", {}) if isinstance(check_input.get("canon", {}), dict) else {}
    facts = _canon_facts(canon)
    claims = check_input.get("claims", []) if isinstance(check_input.get("claims", []), list) else []
    issues: list[dict[str, Any]] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        entity = str(claim.get("entity") or claim.get("name") or claim.get("canonical_name") or claim.get("arc_id") or claim.get("thread_id") or "").strip()
        key = str(claim.get("key") or claim.get("field") or "status").strip()
        value = str(claim.get("value") or "").strip()
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            fact_entity = _canon_fact_name(fact)
            fact_value = _canon_fact_value(fact, key)
            if entity and fact_entity and entity == fact_entity and value and fact_value and value != fact_value:
                issues.append(
                    _canon_issue(
                        f"{entity} 的 {key}={value} 与 Canon={fact_value} 冲突。",
                        "创建正典变更任务或回滚冲突产物。",
                        dimension=str(fact.get("canon_dimension") or claim.get("dimension") or "canon"),
                        evidence_refs=_canon_evidence_refs(fact, canon),
                    )
                )
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        name = _canon_fact_name(fact)
        status = str(fact.get("status") or fact.get("state") or "").strip().lower()
        if not name or not text:
            continue
        if status in {"alive", "存活", "在世"} and name in text and any(term in text for term in ["死了", "死亡", "尸体", "被杀"]):
            issues.append(
                _canon_issue(
                    f"{name} 被 Canon 标记为存活，但文本出现死亡声明。",
                    "回滚死亡声明或提交正典变更。",
                    dimension=str(fact.get("canon_dimension") or "character"),
                    evidence_refs=_canon_evidence_refs(fact, canon),
                )
            )
        if status in {"dead", "死亡", "已死"} and name in text and any(term in text for term in ["还活着", "现身", "开口说"]):
            issues.append(
                _canon_issue(
                    f"{name} 被 Canon 标记为死亡，但文本出现存活行动。",
                    "改为回忆、伪装或提交正典变更。",
                    dimension=str(fact.get("canon_dimension") or "character"),
                    evidence_refs=_canon_evidence_refs(fact, canon),
                )
            )
    for rule in canon.get("rules", []) if isinstance(canon.get("rules", []), list) else []:
        if not isinstance(rule, dict) or not text:
            continue
        for term in _strings(rule.get("forbidden_terms")):
            if term and term in text:
                issues.append(
                    _canon_issue(
                        f"文本命中世界规则禁用项：{term}。",
                        str(rule.get("fix_suggestion") or "改写为符合世界规则的行动或提交 world rule 变更。"),
                        dimension="world_rule",
                        evidence_refs=_canon_evidence_refs(rule, canon),
                    )
                )
    issue_candidates = [canon_conflict_to_issue_candidate(issue, check_input) for issue in issues]
    return {
        "passed": not issues,
        "issues": issues,
        "issue_candidates": issue_candidates,
        "input": {
            "project_id": check_input.get("project_id", ""),
            "target_asset_id": check_input.get("target_asset_id", ""),
            "target_asset_type": check_input.get("target_asset_type", ""),
            "claim_count": len(claims),
        },
        "canon_source": canon.get("source", "payload_or_project_stub"),
        "checked_asset_types": canon.get("checked_asset_types", []),
        "references": canon.get("references", []),
    }


def canon_conflict_to_issue_candidate(issue: dict[str, Any], check_input: dict[str, Any] | None = None) -> dict[str, Any]:
    check_input = check_input or {}
    return {
        "issue_type": "canon_conflict",
        "source_system": "mkaos.canon_conflict",
        "severity": str(issue.get("severity") or "critical"),
        "blocking": bool(issue.get("blocking", True)),
        "message": str(issue.get("message") or ""),
        "fix_suggestion": str(issue.get("fix_suggestion") or ""),
        "target_asset_id": str(check_input.get("target_asset_id") or ""),
        "target_asset_type": str(check_input.get("target_asset_type") or "artifact"),
        "project_id": str(check_input.get("project_id") or "local-system"),
        "dimension": str(issue.get("dimension") or "canon"),
        "evidence_refs": issue.get("evidence_refs", []) if isinstance(issue.get("evidence_refs", []), list) else [],
        "source_issue": issue,
        "status": "open",
    }


def record_usage_event(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    knowledge_ids = _strings(payload.get("knowledge_ids")) or [str(payload.get("knowledge_id") or "")]
    project_id = str(payload.get("project_id") or "local-system")
    flow = _valid_flow(str(payload.get("flow") or "review"))
    os_envelope = _mkaos_envelope(storage, payload, operation="mkaos.usage_event_record", asset_type="knowledge_usage_event", project_id=project_id, task_type=flow)
    events: list[dict[str, Any]] = []
    for knowledge_id in [item for item in knowledge_ids if item]:
        event_id = make_id("knowledge_usage_event", f"{knowledge_id}-{payload.get('knowledge_pack_id', '')}-{utc_now()}")
        content = {
            "event_id": event_id,
            "knowledge_id": knowledge_id,
            "knowledge_pack_id": str(payload.get("knowledge_pack_id") or ""),
            "project_id": project_id,
            "flow": flow,
            "target_artifact_id": str(payload.get("target_artifact_id") or ""),
            "chapter_id": str(payload.get("chapter_id") or ""),
            "agent_name": str(payload.get("agent_name") or "mkaos-adapter"),
            "used_as": str(payload.get("used_as") or payload.get("input_role") or "knowledge_pack_item"),
            "prompt_context": payload.get("prompt_context") if isinstance(payload.get("prompt_context"), dict) else {},
            "output_span": str(payload.get("output_span") or ""),
            "review_result": payload.get("review_result") if isinstance(payload.get("review_result"), dict) else {},
            "reader_feedback": payload.get("reader_feedback") if isinstance(payload.get("reader_feedback"), dict) else {},
            "effect_score": _float(payload.get("effect_score"), 0.0),
            "created_at": utc_now(),
        }
        asset = KnowledgeUsageEvent(
            id=event_id,
            title=f"Usage {knowledge_id} in {content['flow']}",
            source=knowledge_id,
            tags=["mkaos", "knowledge-usage-event", content["flow"]],
            content=content,
            metadata={
                "project_id": content["project_id"],
                "workspace_path": str(payload.get("workspace_path") or ""),
                "mkaos": True,
                "use_in_generation_rag": False,
                "flow": content["flow"],
                "knowledge_pack_id": content["knowledge_pack_id"],
                **envelope_asset_metadata(os_envelope),
            },
            references=_dedupe([knowledge_id, content["knowledge_pack_id"], content["target_artifact_id"]]),
        )
        _ensure_valid(asset.to_dict())
        path = storage.write_asset("runs", asset)
        events.append(_asset_row(storage, path, storage.read_json(path)))
    return {"events": events, "event_count": len(events)}


def record_pack_usage_for_artifact(
    storage: LocalStorage,
    pack_result: dict[str, Any],
    *,
    flow: str,
    target_artifact_id: str,
    chapter_id: str = "",
    agent_name: str = "",
    used_as: str = "knowledge_pack",
    review_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    asset = pack_result.get("asset", {}) if isinstance(pack_result.get("asset", {}), dict) else {}
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    items = content.get("pack_items", []) if isinstance(content.get("pack_items", []), list) else []
    knowledge_ids = _dedupe([str(item.get("knowledge_id", "")) for item in items if isinstance(item, dict)])
    if not knowledge_ids:
        return {"events": [], "event_count": 0}
    return record_usage_event(
        storage,
        {
            "knowledge_ids": knowledge_ids,
            "knowledge_pack_id": str(asset.get("id") or content.get("knowledge_pack_id") or ""),
            "project_id": str(content.get("project_id") or "local-system"),
            "workspace_path": str(content.get("workspace_path") or ""),
            "flow": flow,
            "target_artifact_id": target_artifact_id,
            "chapter_id": chapter_id,
            "agent_name": agent_name or f"{flow}.adapter",
            "used_as": used_as,
            "review_result": review_result or {},
            "effect_score": 0.0,
        },
    )


def list_usage_events(storage: LocalStorage, *, project_id: str | None = None, flow: str | None = None, chapter_id: str | None = None, limit: int = 300) -> list[dict[str, Any]]:
    rows = _list_assets(storage, "runs", "knowledge_usage_event", project_id=project_id, limit=limit)
    if flow:
        rows = [row for row in rows if str(row.get("content", {}).get("flow", "")) == flow]
    if chapter_id:
        rows = [row for row in rows if str(row.get("content", {}).get("chapter_id", "")) == chapter_id]
    return rows


def record_review_feedback(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    knowledge_id = str(payload.get("knowledge_id") or "").strip()
    if not knowledge_id:
        raise ValueError("knowledge_id is required")
    project_id = str(payload.get("project_id") or "local-system")
    flow = str(payload.get("flow") or "review")
    os_envelope = _mkaos_envelope(storage, payload, operation="mkaos.feedback_review", asset_type="knowledge_quality_score", project_id=project_id, task_type=flow)
    delta = _feedback_delta(payload)
    return _record_quality_score(
        storage,
        knowledge_id=knowledge_id,
        flow=flow,
        delta=delta,
        reason=str(payload.get("reason") or "review_feedback"),
        metadata={"feedback": payload, **envelope_asset_metadata(os_envelope)},
    )


def apply_weight_update(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    knowledge_ref = str(payload.get("knowledge_id") or payload.get("knowledge_ref") or "").strip()
    if not knowledge_ref:
        raise ValueError("knowledge_id is required")
    path, data = _find_asset(storage, knowledge_ref, asset_type="knowledge_card", categories=["knowledge"])
    knowledge_id = str(data.get("id", ""))
    flow = str(payload.get("flow") or "review")
    project_id = str(payload.get("project_id") or data.get("metadata", {}).get("project_id") or "local-system")
    os_envelope = _mkaos_envelope(storage, payload, operation="mkaos.feedback_weight_update", asset_type="knowledge_card", project_id=project_id, task_type=flow)
    delta = _feedback_delta(payload)
    if payload.get("deprecated") or str(payload.get("action") or "") == "deprecated":
        delta = min(delta, -0.5)
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    previous = json.loads(json.dumps(data, ensure_ascii=False))
    previous_weight = _float(content.get("weight", metadata.get("weight", 1.0)), 1.0)
    next_weight = max(0.0, round(previous_weight + delta, 4))
    low_events = _low_effect_event_count(storage, knowledge_id, flow)
    status = str(content.get("status") or metadata.get("asset_status") or "active")
    if payload.get("deprecated") or str(payload.get("action") or "") == "deprecated":
        status = "deprecated"
    elif low_events >= 3:
        status = "needs_review"
    content["weight"] = next_weight
    content["status"] = status
    metadata["weight"] = next_weight
    metadata["asset_status"] = status
    metadata.update(envelope_asset_metadata(os_envelope))
    data["content"] = content
    data["metadata"] = metadata
    data["updated_at"] = utc_now()
    storage.write_json(path, data)
    updated = storage.read_json(path)
    record_mkaos_mutation(
        storage,
        asset_type="knowledge_card",
        asset_id=knowledge_id,
        mutation_type="weight_update",
        previous_payload=previous,
        new_payload=updated,
        changed_fields=["content.weight", "metadata.weight", "content.status", "metadata.asset_status"],
        reason=str(payload.get("reason") or "weight_update"),
        actor=str(payload.get("actor") or "mkaos"),
        trace_id=str(os_envelope.get("trace_id") or payload.get("trace_id") or ""),
    )
    score = _record_quality_score(
        storage,
        knowledge_id=knowledge_id,
        flow=flow,
        delta=delta,
        reason=str(payload.get("reason") or "weight_update"),
        metadata={"previous_weight": previous_weight, "next_weight": next_weight, "status": status, "payload": payload, **envelope_asset_metadata(os_envelope)},
    )
    return {"knowledge": {"path": _display_path(storage.root, path), "asset": updated}, "quality_score": score, "delta": delta, "status": status}


def list_risk_knowledge(storage: LocalStorage, *, project_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    rows = list_knowledge_cards(storage, project_id=project_id, include_deprecated=True, limit=limit)
    usage_events = list_usage_events(storage, project_id=project_id, limit=500)
    risky_ids = {
        str(row.get("content", {}).get("knowledge_id", ""))
        for row in usage_events
        if row.get("content", {}).get("review_result", {}).get("anti_encyclopedia_hit") or row.get("content", {}).get("review_result", {}).get("canon_conflict_hit")
    }
    result = []
    for row in rows:
        content = row.get("content", {})
        metadata = row.get("metadata", {})
        status = str(content.get("status") or metadata.get("asset_status") or "")
        risk = str(content.get("risk_level") or metadata.get("risk_level") or "")
        if status in {"deprecated", "needs_review"} or risk in {"high", "critical"} or row.get("id") in risky_ids:
            result.append({**row, "risk_reasons": _risk_reasons(row, risky_ids)})
    return result


def query_knowledge(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    flow = str(payload.get("flow") or payload.get("task_type") or "").strip()
    envelope = _mkaos_envelope(storage, payload, operation="mkaos.query_knowledge", asset_type="knowledge_query", project_id=project_id, task_type=flow or "query")
    rows = list_knowledge_cards(storage, project_id=project_id if project_id != "local-system" else None, include_deprecated=bool(payload.get("include_deprecated", False)), limit=int(payload.get("limit", 100) or 100))
    binding_by_knowledge: dict[str, list[dict[str, Any]]] = {}
    if flow:
        for binding in list_usage_bindings(storage, flow=_valid_flow(flow) if flow in MKAOS_FLOWS else None, enabled=True, limit=1000):
            binding_project = str(binding.get("metadata", {}).get("project_id") or "")
            if not _project_scope_matches(binding_project, project_id):
                continue
            binding_by_knowledge.setdefault(str(binding.get("content", {}).get("knowledge_id", "")), []).append(binding)
        rows = [row for row in rows if row.get("id") in binding_by_knowledge]
    discipline = str(payload.get("discipline") or "").strip().lower()
    if discipline:
        rows = [row for row in rows if discipline in str(row.get("content", {}).get("discipline", "")).lower()]
    query_text = str(payload.get("query") or payload.get("task_goal") or "").strip().lower()
    if query_text:
        terms = [term for term in re.split(r"\s+", query_text) if term]
        rows = [row for row in rows if _knowledge_matches_terms(row, terms)]
    scored = [_query_row(row, binding_by_knowledge.get(str(row.get("id", "")), [])) for row in rows]
    scored.sort(key=lambda row: (-float(row.get("selection_score", 0.0)), str(row.get("title", ""))))
    return envelope_response(
        {
            "items": scored[: int(payload.get("limit", 100) or 100)],
            "count": min(len(scored), int(payload.get("limit", 100) or 100)),
            "total_candidates": len(scored),
            "filters": {"project_id": project_id, "flow": flow, "discipline": discipline, "query": query_text},
        },
        envelope,
    )


def convert_assets(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    envelope = _mkaos_envelope(storage, payload, operation="mkaos.convert_assets", asset_type="knowledge_card", project_id=project_id, task_type=str(payload.get("task_type") or "convert_assets"))
    if payload.get("text") or payload.get("content"):
        source = import_source_document(storage, {**payload, "os_envelope": payload.get("os_envelope") or payload.get("envelope")})
        chunks = source["chunks"]
    else:
        source_ref = str(payload.get("source_id") or payload.get("source_path") or payload.get("source_ref") or "")
        if not source_ref:
            raise ValueError("source_id, source_path, source_ref, or text is required")
        chunks = list_source_chunks(storage, source_ref, project_id=project_id if project_id != "local-system" else None)
        if not chunks:
            chunks = rebuild_source_chunks(storage, source_ref)["chunks"]
    concepts = payload.get("concepts") if isinstance(payload.get("concepts"), list) else []
    if not concepts:
        concepts = [{"concept_name": payload.get("concept_name") or "Converted knowledge", "core_explanation": payload.get("core_explanation") or "Abstract reusable knowledge converted from source evidence."}]
    knowledge: list[dict[str, Any]] = []
    chunk_ids = [str(chunk.get("id", "")) for chunk in chunks if str(chunk.get("id", "")).strip()]
    for item in concepts:
        if not isinstance(item, dict):
            continue
        knowledge.append(
            create_knowledge_card(
                storage,
                {
                    **item,
                    "source_chunk_ids": item.get("source_chunk_ids") or chunk_ids[: int(item.get("chunk_limit", 3) or 3)],
                    "project_id": project_id,
                    "workspace_path": payload.get("workspace_path", ""),
                    "os_envelope": payload.get("os_envelope") or payload.get("envelope"),
                    "environment": payload.get("environment", ""),
                    "bypass_reason": payload.get("bypass_reason", ""),
                    "source_policy": payload.get("source_policy", {}),
                },
            )
        )
    return envelope_response({"knowledge": knowledge, "chunk_count": len(chunks), "source_chunk_ids": chunk_ids}, envelope)


def convert_rules(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    envelope = _mkaos_envelope(storage, payload, operation="mkaos.convert_rules", asset_type="rule_card", project_id=project_id, task_type=str(payload.get("task_type") or "convert_rules"))
    knowledge_ref = str(payload.get("knowledge_id") or payload.get("knowledge_ref") or "").strip()
    if not knowledge_ref:
        raise ValueError("knowledge_id or knowledge_ref is required")
    _, knowledge = _find_asset(storage, knowledge_ref, asset_type="knowledge_card", categories=["knowledge"])
    content = knowledge.get("content", {}) if isinstance(knowledge.get("content", {}), dict) else {}
    concept = str(content.get("concept_name") or knowledge.get("title") or knowledge_ref)
    rule = create_rule_card(
        storage,
        {
            "rule_name": str(payload.get("rule_name") or f"{concept} 有效性规则"),
            "rule_type": str(payload.get("rule_type") or "knowledge_effectiveness"),
            "trigger_condition": str(payload.get("trigger_condition") or f"{concept} 进入生成或审稿"),
            "check_items": payload.get("check_items") or ["知识必须改变角色选择、代价或审稿判断"],
            "severity": str(payload.get("severity") or "medium"),
            "blocking": bool(payload.get("blocking", False)),
            "fix_suggestion": str(payload.get("fix_suggestion") or "把知识改写为行动、冲突、物件或审稿规则。"),
            "applicable_flows": payload.get("applicable_flows") or ["review"],
            "project_id": project_id,
            "workspace_path": payload.get("workspace_path", ""),
            "os_envelope": payload.get("os_envelope") or payload.get("envelope"),
            "environment": payload.get("environment", ""),
            "bypass_reason": payload.get("bypass_reason", ""),
            "source_policy": payload.get("source_policy", {}),
        },
    )
    template = None
    if payload.get("create_template"):
        template = create_template_card(
            storage,
            {
                "template_name": str(payload.get("template_name") or f"{concept} 场景模板"),
                "template_type": "knowledge_application",
                "structure": payload.get("structure") or ["pressure", "choice", "cost", "payoff"],
                "applicable_flows": payload.get("template_flows") or ["outline", "chapter_outline"],
                "project_id": project_id,
                "workspace_path": payload.get("workspace_path", ""),
                "os_envelope": payload.get("os_envelope") or payload.get("envelope"),
                "environment": payload.get("environment", ""),
                "bypass_reason": payload.get("bypass_reason", ""),
                "source_policy": payload.get("source_policy", {}),
            },
        )
    return envelope_response({"rule": rule, "template": template}, envelope)


def build_knowledge_graph(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    flow = str(payload.get("flow") or payload.get("task_type") or "").strip()
    envelope = _mkaos_envelope(
        storage,
        payload,
        operation="mkaos.knowledge_graph_build",
        asset_type="knowledge_graph_snapshot",
        project_id=project_id,
        task_type=flow or "knowledge_graph",
    )
    content = _knowledge_graph_content(
        storage,
        project_id=project_id,
        flow=flow,
        discipline=str(payload.get("discipline") or ""),
        include_deprecated=bool(payload.get("include_deprecated", False)),
        limit=int(payload.get("limit", 500) or 500),
    )
    content["envelope_id"] = envelope.get("envelope_id", "")
    content["trace_id"] = envelope.get("trace_id", "")
    if bool(payload.get("persist", False)):
        path = _persist_knowledge_graph_snapshot(storage, content, envelope)
        content["path"] = _display_path(storage.root, path)
        content["asset_id"] = storage.read_json(path).get("id", "")
    return envelope_response(content, envelope)


def build_knowledge_graph_explorer(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    flow = str(payload.get("flow") or payload.get("task_type") or "").strip()
    envelope = _mkaos_envelope(
        storage,
        payload,
        operation="mkaos.knowledge_graph_explorer",
        asset_type="knowledge_graph_explorer_report",
        project_id=project_id,
        task_type=flow or "knowledge_graph_explorer",
    )
    graph = _knowledge_graph_content(
        storage,
        project_id=project_id,
        flow=flow,
        discipline=str(payload.get("discipline") or ""),
        include_deprecated=bool(payload.get("include_deprecated", False)),
        limit=int(payload.get("limit", 500) or 500),
    )
    explorer = _knowledge_graph_explorer_content(graph, max_nodes=int(payload.get("max_nodes", 80) or 80), max_frames=int(payload.get("max_frames", 32) or 32))
    explorer["envelope_id"] = envelope.get("envelope_id", "")
    explorer["trace_id"] = envelope.get("trace_id", "")
    if bool(payload.get("persist", False)):
        asset = _base_asset(
            "knowledge_graph_explorer_report",
            asset_id=explorer["explorer_report_id"],
            title=f"MKAOS graph explorer {project_id} {flow or 'all'}",
            source="mkaos-knowledge-graph-explorer",
            tags=["mkaos", "knowledge-graph-explorer", flow or "all"],
            content=explorer,
            metadata={"project_id": project_id, "mkaos": True, "use_in_generation_rag": False, **envelope_asset_metadata(envelope)},
            references=_dedupe([str(node.get("asset_id") or "") for node in explorer.get("nodes", []) if str(node.get("asset_id") or "").strip()]),
        )
        path = storage.write_asset("runs", asset)
        explorer["path"] = _display_path(storage.root, path)
        explorer["asset_id"] = asset.id
    return envelope_response(explorer, envelope)


def query_knowledge_graph(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    flow = str(payload.get("flow") or payload.get("task_type") or "").strip()
    envelope = _mkaos_envelope(
        storage,
        payload,
        operation="mkaos.knowledge_graph_query",
        asset_type="knowledge_graph_query",
        project_id=project_id,
        task_type=flow or "knowledge_graph_query",
    )
    graph = _knowledge_graph_content(
        storage,
        project_id=project_id,
        flow=flow,
        discipline=str(payload.get("discipline") or ""),
        include_deprecated=bool(payload.get("include_deprecated", False)),
        limit=int(payload.get("limit", 500) or 500),
    )
    terms = [term for term in re.split(r"\s+", str(payload.get("query") or payload.get("term") or "").strip().lower()) if term]
    node_by_id = {str(node.get("id")): node for node in graph["nodes"]}
    if terms:
        matched_ids = {node_id for node_id, node in node_by_id.items() if _graph_node_matches_terms(node, terms)}
    else:
        node_types = set(_strings(payload.get("node_types")))
        matched_ids = {
            node_id
            for node_id, node in node_by_id.items()
            if not node_types or str(node.get("node_type") or "") in node_types
        }
    include_neighbors = int(payload.get("include_neighbors", 1) or 0)
    visible_ids = set(matched_ids)
    visible_edges: list[dict[str, Any]] = []
    for _ in range(max(0, include_neighbors)):
        for edge in graph["edges"]:
            source = str(edge.get("source") or "")
            target = str(edge.get("target") or "")
            if source in visible_ids or target in visible_ids:
                visible_ids.update([source, target])
    for edge in graph["edges"]:
        if str(edge.get("source") or "") in visible_ids and str(edge.get("target") or "") in visible_ids:
            visible_edges.append(edge)
    result = {
        "graph_id": graph["graph_id"],
        "project_id": graph["project_id"],
        "query": " ".join(terms),
        "matched_node_ids": sorted(matched_ids),
        "nodes": [node_by_id[node_id] for node_id in sorted(visible_ids) if node_id in node_by_id],
        "edges": visible_edges,
        "summary": graph["summary"],
        "source_isolation": graph["source_isolation"],
    }
    return envelope_response(result, envelope)


def query_knowledge_graph_paths(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    flow = str(payload.get("flow") or payload.get("task_type") or "").strip()
    envelope = _mkaos_envelope(
        storage,
        payload,
        operation="mkaos.knowledge_graph_paths",
        asset_type="knowledge_graph_path_query",
        project_id=project_id,
        task_type=flow or "knowledge_graph_paths",
    )
    graph = _knowledge_graph_content(
        storage,
        project_id=project_id,
        flow=flow,
        discipline=str(payload.get("discipline") or ""),
        include_deprecated=bool(payload.get("include_deprecated", False)),
        limit=int(payload.get("limit", 500) or 500),
    )
    source = str(payload.get("source") or payload.get("source_id") or "").strip()
    target = str(payload.get("target") or payload.get("target_id") or "").strip()
    if not source or not target:
        raise ValueError("source and target are required")
    max_depth = max(1, int(payload.get("max_depth", 4) or 4))
    paths = _find_graph_paths(graph, source, target, max_depth=max_depth)
    return envelope_response(
        {
            "graph_id": graph["graph_id"],
            "project_id": project_id,
            "source": source,
            "target": target,
            "max_depth": max_depth,
            "paths": paths,
            "path_count": len(paths),
            "source_isolation": graph["source_isolation"],
        },
        envelope,
    )


def learn_from_knowledge_effects(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    flow = str(payload.get("flow") or payload.get("task_type") or "").strip()
    envelope = _mkaos_envelope(
        storage,
        payload,
        operation="mkaos.knowledge_effect_learning",
        asset_type="knowledge_learning_snapshot",
        project_id=project_id,
        task_type=flow or "knowledge_effect_learning",
    )
    snapshot = _knowledge_learning_content(
        storage,
        project_id=project_id,
        flow=flow,
        discipline=str(payload.get("discipline") or ""),
        include_deprecated=bool(payload.get("include_deprecated", False)),
        learning_rate=_float(payload.get("learning_rate"), 0.25),
        limit=int(payload.get("limit", 500) or 500),
    )
    applied_updates: list[dict[str, Any]] = []
    if bool(payload.get("apply_updates", False)):
        min_delta = abs(_float(payload.get("min_apply_delta"), 0.03))
        for item in snapshot["learning_items"]:
            delta = _float(item.get("recommended_weight_delta"), 0.0)
            if abs(delta) < min_delta:
                continue
            update = apply_weight_update(
                storage,
                {
                    "project_id": project_id,
                    "knowledge_id": item["knowledge_id"],
                    "flow": item.get("flow") or flow or "review",
                    "delta": delta,
                    "reason": "knowledge_effect_learning",
                    "os_envelope": payload.get("os_envelope") or payload.get("envelope"),
                    "environment": payload.get("environment", ""),
                    "bypass_reason": payload.get("bypass_reason", ""),
                    "source_policy": payload.get("source_policy", {}),
                },
            )
            updated_content = update.get("knowledge", {}).get("asset", {}).get("content", {})
            applied_updates.append(
                {
                    "knowledge_id": item["knowledge_id"],
                    "concept_name": item["concept_name"],
                    "flow": item.get("flow") or flow or "review",
                    "applied_delta": delta,
                    "next_weight": updated_content.get("weight"),
                    "status": update.get("status", ""),
                    "quality_score_path": update.get("quality_score", {}).get("path", ""),
                }
            )
    snapshot["applied_updates"] = applied_updates
    snapshot["envelope_id"] = envelope.get("envelope_id", "")
    snapshot["trace_id"] = envelope.get("trace_id", "")
    if bool(payload.get("persist", True)) or applied_updates:
        path = _persist_knowledge_learning_snapshot(storage, snapshot, envelope)
        snapshot["path"] = _display_path(storage.root, path)
        snapshot["asset_id"] = storage.read_json(path).get("id", "")
    return envelope_response(snapshot, envelope)


def run_knowledge_evolution_cycle(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    """Run the deterministic MKAOS knowledge-asset evolution loop.

    The default mode is advisory: it persists an auditable report and candidate
    assets, but it does not change active weights/status/rules unless the caller
    explicitly opts into the corresponding apply flags.
    """

    project_id = str(payload.get("project_id") or "local-system")
    flow = str(payload.get("flow") or payload.get("task_type") or "").strip()
    envelope = _mkaos_envelope(
        storage,
        payload,
        operation="mkaos.knowledge_evolution_cycle",
        asset_type="knowledge_evolution_report",
        project_id=project_id,
        task_type=flow or "knowledge_evolution",
    )
    common_payload = {
        "project_id": project_id,
        "flow": flow,
        "discipline": payload.get("discipline", ""),
        "include_deprecated": bool(payload.get("include_deprecated", False)),
        "limit": int(payload.get("limit", 500) or 500),
        "os_envelope": payload.get("os_envelope") or payload.get("envelope"),
        "environment": payload.get("environment", ""),
        "bypass_reason": payload.get("bypass_reason", ""),
        "source_policy": payload.get("source_policy", {}),
    }
    graph_response = build_knowledge_graph(storage, {**common_payload, "persist": bool(payload.get("persist_graph", True))})
    graph = _response_data(graph_response)
    learning_response = learn_from_knowledge_effects(
        storage,
        {
            **common_payload,
            "persist": True,
            "learning_rate": _float(payload.get("learning_rate"), 0.25),
            "apply_updates": bool(payload.get("apply_updates", False)),
            "min_apply_delta": _float(payload.get("min_apply_delta"), 0.03),
        },
    )
    learning = _response_data(learning_response)
    attributions = _list_assets(storage, "feedback", "knowledge_feedback_attribution", project_id=project_id if project_id != "local-system" else None, limit=1000)
    production = _mkaos_payload_is_production(payload)
    evolution_mode = str(payload.get("evolution_mode") or ("production_guarded" if production and payload.get("auto_apply_policy") else "advisory"))
    auto_apply_safe_actions = evolution_mode in {"guarded_auto", "production_guarded"} or bool(payload.get("auto_apply_safe_actions", False))
    governance_payload = {
        **payload,
        "evolution_mode": evolution_mode,
        "auto_apply_safe_actions": auto_apply_safe_actions,
        "auto_rule_activation_threshold": _float(payload.get("auto_rule_activation_threshold"), 0.65),
        "auto_template_activation_threshold": _float(payload.get("auto_template_activation_threshold"), 0.7),
        "auto_elimination_threshold": int(payload.get("auto_elimination_threshold", 3) or 3),
    }
    rule_evolution = _evolve_review_rules_from_learning(storage, project_id, flow, learning, attributions, governance_payload)
    template_backflow = _backflow_templates_from_learning(storage, project_id, flow, learning, governance_payload)
    elimination = _low_effect_knowledge_elimination(storage, project_id, flow, learning, governance_payload)
    approval_workflow = _create_evolution_approval_requests(
        storage,
        project_id,
        flow,
        rule_evolution,
        template_backflow,
        elimination,
        governance_payload,
    )
    content = {
        "evolution_report_id": _stable_asset_id(
            "knowledge_evolution_report",
            project_id,
            flow or "all",
            str(len(learning.get("learning_items", []))),
            str(len(rule_evolution.get("candidates", []))),
            str(len(template_backflow.get("candidates", []))),
        ),
        "project_id": project_id,
        "flow": flow,
        "version": "mkaos-knowledge-evolution-v1",
        "graph_snapshot": {
            "graph_id": graph.get("graph_id", ""),
            "asset_id": graph.get("asset_id", ""),
            "summary": graph.get("summary", {}),
            "source_isolation": graph.get("source_isolation", {}),
        },
        "learning_snapshot": {
            "learning_id": learning.get("learning_id", ""),
            "asset_id": learning.get("asset_id", ""),
            "source_metrics": learning.get("source_metrics", {}),
            "recommendation_count": len(learning.get("recommendations", [])),
            "applied_update_count": len(learning.get("applied_updates", [])),
        },
        "review_rule_evolution": rule_evolution,
        "hot_template_backflow": template_backflow,
        "reader_feedback_backflow": {
            "attribution_count": len(attributions),
            "negative_count": len([row for row in attributions if row.get("content", {}).get("sentiment") == "negative"]),
            "positive_count": len([row for row in attributions if row.get("content", {}).get("sentiment") == "positive"]),
            "top_tags": _top_feedback_tags(attributions),
        },
        "low_effect_elimination": elimination,
        "approval_workflow": approval_workflow,
        "governance_policy": {
            "default_mode": "advisory",
            "evolution_mode": evolution_mode,
            "auto_apply_safe_actions": auto_apply_safe_actions,
            "auto_rule_activation_threshold": governance_payload["auto_rule_activation_threshold"],
            "auto_template_activation_threshold": governance_payload["auto_template_activation_threshold"],
            "auto_elimination_threshold": governance_payload["auto_elimination_threshold"],
            "apply_weight_updates": bool(payload.get("apply_updates", False)),
            "apply_rule_updates": bool(payload.get("apply_rule_updates", False)),
            "apply_template_updates": bool(payload.get("apply_template_updates", False)),
            "apply_elimination": bool(payload.get("apply_elimination", False)),
            "production_fail_closed": production,
            "automatic_destructive_actions_require_guarded_policy": True,
            "human_approval_available": True,
            "human_approval_requested": bool(approval_workflow.get("approval_count", 0)),
        },
        "source_isolation": {"raw_text_included": False, "clean_text_included": False, "evidence_refs_only": True},
        "created_at": utc_now(),
        "envelope_id": envelope.get("envelope_id", ""),
        "trace_id": envelope.get("trace_id", ""),
    }
    asset = _base_asset(
        "knowledge_evolution_report",
        asset_id=content["evolution_report_id"],
        title=f"MKAOS knowledge evolution {project_id} {flow or 'all'}",
        source="mkaos-knowledge-evolution",
        tags=["mkaos", "knowledge-evolution", flow or "all"],
        content=content,
        metadata={"project_id": project_id, "mkaos": True, "use_in_generation_rag": False, **envelope_asset_metadata(envelope)},
        references=_dedupe(
            [
                str(graph.get("asset_id") or graph.get("graph_id") or ""),
                str(learning.get("asset_id") or learning.get("learning_id") or ""),
                *[str(item.get("candidate_id") or item.get("asset_id") or "") for item in rule_evolution.get("candidates", [])],
                *[str(item.get("candidate_id") or item.get("asset_id") or "") for item in template_backflow.get("candidates", [])],
            ]
        ),
    )
    path = storage.write_asset("runs", asset)
    content["path"] = _display_path(storage.root, path)
    content["asset_id"] = asset.id
    return envelope_response(content, envelope)


def create_governance_approval(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    action_type = str(payload.get("action_type") or payload.get("approval_type") or "governance_action")
    envelope = _mkaos_envelope(
        storage,
        payload,
        operation="mkaos.governance_approval_create",
        asset_type="knowledge_governance_approval",
        project_id=project_id,
        task_type=action_type,
    )
    content = {
        "approval_id": str(payload.get("approval_id") or _stable_asset_id("knowledge_governance_approval", project_id, action_type, json.dumps(payload.get("action_payload", {}), ensure_ascii=False, sort_keys=True))),
        "project_id": project_id,
        "flow": str(payload.get("flow") or ""),
        "approval_type": str(payload.get("approval_type") or action_type),
        "action_type": action_type,
        "status": "pending",
        "risk_level": str(payload.get("risk_level") or "medium"),
        "reason": str(payload.get("reason") or ""),
        "requested_by": str(payload.get("actor") or "mkaos"),
        "source_report_id": str(payload.get("source_report_id") or ""),
        "action_payload": payload.get("action_payload") if isinstance(payload.get("action_payload"), dict) else {},
        "decision": {},
        "applied_result": {},
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
        "created_at": utc_now(),
        "envelope_id": envelope.get("envelope_id", ""),
        "trace_id": envelope.get("trace_id", ""),
    }
    asset = _base_asset(
        "knowledge_governance_approval",
        asset_id=content["approval_id"],
        title=f"MKAOS approval {content['action_type']}",
        source=content["source_report_id"] or "mkaos-governance",
        tags=["mkaos", "governance-approval", "pending", content["action_type"]],
        content=content,
        metadata={"project_id": project_id, "mkaos": True, "asset_status": "pending", "use_in_generation_rag": False, **envelope_asset_metadata(envelope)},
        references=_dedupe(_strings(payload.get("references"))),
    )
    path = storage.write_asset("runs", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def list_governance_approvals(storage: LocalStorage, *, project_id: str | None = None, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows = _list_assets(storage, "runs", "knowledge_governance_approval", project_id=project_id, limit=limit)
    if status:
        rows = [row for row in rows if str(row.get("content", {}).get("status") or "") == status]
    return rows


def resolve_governance_approval(storage: LocalStorage, approval_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    path, approval = _find_asset(storage, approval_id, asset_type="knowledge_governance_approval", categories=["runs"])
    content = approval.get("content", {}) if isinstance(approval.get("content"), dict) else {}
    status = str(payload.get("status") or payload.get("decision") or "approved").strip().lower()
    if status not in {"approved", "rejected"}:
        raise ValueError("governance approval status must be approved or rejected")
    content["status"] = status
    content["decision"] = {
        "status": status,
        "actor": str(payload.get("actor") or "operator"),
        "reason": str(payload.get("reason") or ""),
        "decided_at": utc_now(),
    }
    applied: dict[str, Any] = {}
    if status == "approved" and bool(payload.get("apply", False)):
        applied = _apply_governance_approval_action(storage, content, payload)
        content["status"] = "applied" if applied.get("applied", False) else "approved"
    content["applied_result"] = applied
    approval["content"] = _strip_source_text_fields(content)
    metadata = approval.get("metadata", {}) if isinstance(approval.get("metadata"), dict) else {}
    metadata["asset_status"] = content["status"]
    approval["metadata"] = metadata
    approval["updated_at"] = utc_now()
    storage.write_json(path, approval)
    record_mkaos_mutation(
        storage,
        asset_type="knowledge_governance_approval",
        asset_id=str(approval.get("id") or approval_id),
        mutation_type="status_change",
        previous_payload={},
        new_payload=approval,
        reason="resolve_governance_approval",
        actor=str(payload.get("actor") or "operator"),
        trace_id=str(payload.get("trace_id") or content.get("trace_id") or ""),
    )
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path), "applied": applied}


def run_mkaos_provider_e2e_probe(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    envelope = _mkaos_envelope(
        storage,
        payload,
        operation="mkaos.provider_e2e_probe",
        asset_type="mkaos_provider_e2e_probe_report",
        project_id=project_id,
        task_type=str(payload.get("task_type") or "provider_e2e_probe"),
    )
    provider = payload.get("provider") if isinstance(payload.get("provider"), dict) else {}
    provider_mode = str(payload.get("provider_mode") or provider.get("mode") or "mock")
    probe_type = str(payload.get("probe_type") or "both")
    opt_in = bool(payload.get("provider_opt_in") or provider.get("opt_in") or os.environ.get("NOVEL_FORGE_MKAOS_PROVIDER_E2E") == "1")
    online_requested = provider_mode in {"online", "external", "model"} or bool(payload.get("online", False))
    online_enabled = os.environ.get("NOVEL_FORGE_MKAOS_PROVIDER_E2E") == "1"
    model_probe: dict[str, Any] = {"requested": probe_type in {"both", "model_judge"}, "status": "not_requested"}
    extraction_probe: dict[str, Any] = {"requested": probe_type in {"both", "extraction_provider"}, "status": "not_requested"}
    if not opt_in:
        status = "opt_in_required"
    elif online_requested and not online_enabled:
        status = "online_disabled"
    else:
        status = "completed"
    if model_probe["requested"]:
        if status == "completed":
            model_payload = payload.get("model_judge_payload") if isinstance(payload.get("model_judge_payload"), dict) else {}
            model_result = payload.get("model_judge_result") if isinstance(payload.get("model_judge_result"), dict) else model_payload.get("model_judge_result") if isinstance(model_payload.get("model_judge_result"), dict) else {"conflicts": []}
            model_report = detect_knowledge_conflicts(
                storage,
                {
                    **model_payload,
                    "project_id": project_id,
                    "persist": False,
                    "enable_model_judge": True,
                    "model_judge_opt_in": True,
                    "model_judge_result": model_result,
                },
            )
            model_probe = {"requested": True, "status": "completed", "blocking_count": model_report.get("blocking_count", 0), "conflict_count": len(model_report.get("conflicts", [])), "model_judge": model_report.get("model_judge", {})}
        else:
            model_probe = {"requested": True, "status": status}
    if extraction_probe["requested"]:
        if status == "completed":
            extraction_payload = payload.get("extraction_payload") if isinstance(payload.get("extraction_payload"), dict) else {}
            candidates = extraction_payload.get("candidates") if isinstance(extraction_payload.get("candidates"), list) else payload.get("mock_provider_candidates") if isinstance(payload.get("mock_provider_candidates"), list) else []
            quality = _response_data(
                validate_extraction_provider_quality(
                    storage,
                    {
                        **extraction_payload,
                        "project_id": project_id,
                        "provider_mode": "model_assisted",
                        "provider_status": "mock_provider_ready" if provider_mode == "mock" else "external_provider_ready",
                        "provider_opt_in": True,
                        "candidates": candidates,
                        "persist": False,
                    },
                )
            )
            extraction_probe = {"requested": True, "status": "completed", "passed": quality.get("passed", False), "average_quality_score": quality.get("average_quality_score", 0), "issue_count": len(quality.get("issues", [])), "quality_report": quality}
        else:
            extraction_probe = {"requested": True, "status": status}
    passed = status == "completed" and all(
        not probe.get("requested") or probe.get("status") == "completed" and probe.get("passed", True) is not False
        for probe in [model_probe, extraction_probe]
    )
    content = {
        "probe_report_id": _stable_asset_id("mkaos_provider_e2e_probe", project_id, provider_mode, probe_type, status),
        "project_id": project_id,
        "provider": provider.get("name") or payload.get("provider_name") or "mock_or_local",
        "provider_mode": provider_mode,
        "probe_type": probe_type,
        "opt_in": opt_in,
        "online_requested": online_requested,
        "online_enabled": online_enabled,
        "status": status,
        "passed": passed,
        "model_judge_probe": model_probe,
        "extraction_provider_probe": extraction_probe,
        "network_policy": "no_external_call_without_NOVEL_FORGE_MKAOS_PROVIDER_E2E",
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
        "created_at": utc_now(),
        "envelope_id": envelope.get("envelope_id", ""),
        "trace_id": envelope.get("trace_id", ""),
    }
    if bool(payload.get("persist", True)):
        asset = _base_asset(
            "mkaos_provider_e2e_probe_report",
            asset_id=content["probe_report_id"],
            title="MKAOS provider E2E probe",
            source="mkaos-provider-e2e",
            tags=["mkaos", "provider-e2e", status],
            content=content,
            metadata={"project_id": project_id, "mkaos": True, "use_in_generation_rag": False, **envelope_asset_metadata(envelope)},
            references=_dedupe(_strings(payload.get("references"))),
        )
        path = storage.write_asset("runs", asset)
        content["path"] = _display_path(storage.root, path)
        content["asset_id"] = asset.id
    return envelope_response(content, envelope)


def run_minimal_acceptance_fixture(storage: LocalStorage) -> dict[str, Any]:
    source = import_source_document(
        storage,
        {
            "title": "土地兼并制度知识样例",
            "text": "王朝末期，土地兼并严重，小农破产，流民增加，地方豪强扩张，中央税源减少。",
            "source_kind": "manual_note",
            "project_id": "mkaos-p0-fixture",
        },
    )
    chunk_ids = [row["id"] for row in source["chunks"]]
    knowledge = create_knowledge_card(
        storage,
        {
            "concept_name": "土地兼并",
            "concept_aliases": ["田契集中", "豪强扩张"],
            "discipline": "历史制度",
            "sub_discipline": "土地制度",
            "knowledge_type": "conflict_mechanism",
            "core_explanation": "土地兼并通过田契、税源和佃户关系改变地方利益分配，适合转化为豪强获利、小农受损、主角被案卷卷入的主线冲突。",
            "source_chunk_ids": chunk_ids,
            "project_id": "mkaos-p0-fixture",
            "applicable_genres": ["历史", "权谋", "悬疑"],
            "applicable_platforms": ["local"],
        },
    )
    rule = create_rule_card(
        storage,
        {
            "rule_name": "制度知识是否推动人物利益冲突",
            "rule_type": "institutional_effectiveness",
            "trigger_condition": "制度知识进入故事生产",
            "check_items": ["豪强获利", "小农受损", "主角因田契案卷入"],
            "severity": "high",
            "blocking": False,
            "fix_suggestion": "把制度说明改成田契案、县衙案卷、粮仓和佃户行动。",
            "applicable_flows": ["outline", "chapter_outline", "prose", "review"],
            "project_id": "mkaos-p0-fixture",
        },
    )
    template = create_template_card(
        storage,
        {
            "template_name": "地方土地案主线模板",
            "template_type": "main_conflict",
            "structure": ["田契异常", "小农破产", "豪强扩张", "县衙税源压力", "主角卷入案卷"],
            "usage_constraints": ["地方土地案作为第一卷主线冲突", "制度矛盾必须影响主角利益", "反派必须有经济和权力动机"],
            "applicable_flows": ["outline", "chapter_outline"],
            "project_id": "mkaos-p0-fixture",
        },
    )
    knowledge_id = knowledge["asset"]["id"]
    bindings = [
        create_usage_binding(storage, knowledge_id, {"flow": "outline", "usage_type": "required", "input_role": "required", "output_form": "主线结构约束", "constraint_text": "地方土地案作为第一卷主线冲突；制度矛盾必须影响主角利益；反派必须有经济和权力动机。", "template_id": template["asset"]["id"], "priority": 10}),
        create_usage_binding(storage, knowledge_id, {"flow": "chapter_outline", "usage_type": "required", "input_role": "required", "output_form": "章节事件与场景冲突", "constraint_text": "每章必须把田契、佃户、县衙或粮仓之一转成行动闭环。", "priority": 20}),
        create_usage_binding(storage, knowledge_id, {"flow": "prose", "usage_type": "optional", "input_role": "optional", "output_form": "动作、物件、对话、场景变化", "prompt_fragment": "允许使用：田契、县衙、粮仓、佃户。", "constraint_text": "禁止大段解释土地制度；知识必须转成动作、物件、对话或场景变化。", "priority": 30}),
        create_usage_binding(storage, knowledge_id, {"flow": "review", "usage_type": "review_rule", "input_role": "review_rule", "output_form": "审稿检查项", "constraint_text": "检查制度知识是否推动人物利益冲突。", "review_rule_id": rule["asset"]["id"], "priority": 10}),
    ]
    packs = {
        flow: build_knowledge_pack(
            storage,
            {
                "flow": flow,
                "task_id": f"fixture-{flow}",
                "project_id": "mkaos-p0-fixture",
                "genre": "历史",
                "platform": "local",
                "chapter_id": "1",
                "current_goal": "证明土地兼并知识进入生产闭环",
            },
        )
        for flow in ["outline", "chapter_outline", "prose", "review"]
    }
    usage = record_usage_event(
        storage,
        {
            "knowledge_id": knowledge_id,
            "knowledge_pack_id": packs["prose"]["asset"]["id"],
            "project_id": "mkaos-p0-fixture",
            "flow": "prose",
            "chapter_id": "1",
            "agent_name": "ProseAgent",
            "used_as": "object_and_scene_constraint",
            "effect_score": 0.8,
        },
    )
    feedback = record_review_feedback(storage, {"knowledge_id": knowledge_id, "flow": "review", "conflict_effective": True, "reason": "fixture_review_passed"})
    return {
        "source": source,
        "knowledge_card": knowledge,
        "bindings": bindings,
        "rule_card": rule,
        "template_card": template,
        "packs": packs,
        "usage": usage,
        "feedback": feedback,
        "acceptance": {
            "knowledge_enters_outline": bool(packs["outline"]["asset"]["content"]["required_knowledge"]),
            "knowledge_enters_chapter_outline": bool(packs["chapter_outline"]["asset"]["content"]["required_knowledge"]),
            "knowledge_enters_prose": bool(packs["prose"]["asset"]["content"]["optional_knowledge"] or packs["prose"]["asset"]["content"]["required_knowledge"]),
            "knowledge_enters_review": bool(packs["review"]["asset"]["content"]["review_rules"]),
            "prose_source_isolation": not _contains_key(packs["prose"]["asset"]["content"], "raw_text"),
        },
    }


def create_evidence_span(storage: LocalStorage, source_chunk_ref: str | Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    path, chunk = _find_asset(storage, source_chunk_ref, asset_type="source_chunk", categories=["raw"])
    content = chunk.get("content", {}) if isinstance(chunk.get("content", {}), dict) else {}
    metadata = chunk.get("metadata", {}) if isinstance(chunk.get("metadata", {}), dict) else {}
    project_id = str(payload.get("project_id") or metadata.get("project_id") or "local-system")
    span = {
        "source_document_id": str(content.get("source_document_id") or ""),
        "source_chunk_id": str(chunk.get("id") or ""),
        "source_chunk_path": _display_path(storage.root, path),
        "page_start": payload.get("page_start"),
        "page_end": payload.get("page_end"),
        "chapter_title": payload.get("chapter_title"),
        "section_title": payload.get("section_title"),
        "paragraph_start": payload.get("paragraph_start"),
        "paragraph_end": payload.get("paragraph_end"),
        "sentence_start": payload.get("sentence_start"),
        "sentence_end": payload.get("sentence_end"),
        "char_start": payload.get("char_start"),
        "char_end": payload.get("char_end"),
        "extractor_id": str(payload.get("extractor_id") or "mkaos.deterministic"),
        "extraction_method": str(payload.get("extraction_method") or "deterministic"),
    }
    span["evidence_hash"] = _hash_text(json.dumps({**span, "content_hash": content.get("content_hash", "")}, ensure_ascii=False, sort_keys=True))
    asset = _base_asset(
        "evidence_span",
        title=f"Evidence span {span['source_chunk_id']}",
        source=span["source_chunk_id"],
        tags=["mkaos", "evidence-span"],
        content={"span_id": "", **span, "source_isolation": {"raw_text_included": False, "clean_text_included": False}},
        metadata={"project_id": project_id, "mkaos": True, "evidence_layer_only": True, "use_in_generation_rag": False},
        references=_dedupe([span["source_document_id"], span["source_chunk_id"], span["source_chunk_path"]]),
    )
    asset.id = _stable_asset_id("evidence_span", span["source_chunk_id"], span["evidence_hash"])
    asset.content["span_id"] = asset.id
    _ensure_valid(asset.to_dict())
    written = storage.write_asset("raw", asset)
    record_mkaos_mutation(
        storage,
        asset_type="evidence_span",
        asset_id=asset.id,
        mutation_type="create",
        new_payload=asset.to_dict(),
        reason=str(payload.get("reason") or "create_evidence_span"),
        actor=str(payload.get("actor") or "mkaos"),
        trace_id=str(payload.get("trace_id") or ""),
    )
    return {"path": _display_path(storage.root, written), "asset": storage.read_json(written)}


def list_evidence_spans(storage: LocalStorage, *, source_chunk_id: str | None = None, project_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    rows = _list_assets(storage, "raw", "evidence_span", project_id=project_id, limit=limit)
    if source_chunk_id:
        rows = [row for row in rows if str(row.get("content", {}).get("source_chunk_id") or "") == source_chunk_id]
    return rows


def recalculate_knowledge_quality(storage: LocalStorage, knowledge_ref: str | Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    path, data = _find_asset(storage, knowledge_ref, asset_type="knowledge_card", categories=["knowledge"])
    previous = json.loads(json.dumps(data, ensure_ascii=False))
    knowledge_id = str(data.get("id") or "")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    dimensions = _quality_dimensions(content.get("quality_dimensions") if isinstance(content.get("quality_dimensions"), dict) else content)
    history = knowledge_quality_history(storage, knowledge_id, limit=500)
    usage = [row for row in list_usage_events(storage, project_id=str(data.get("metadata", {}).get("project_id") or None), limit=1000) if str(row.get("content", {}).get("knowledge_id") or "") == knowledge_id]
    if history["count"]:
        delta = sum(_float(row.get("content", {}).get("delta"), 0.0) for row in history["items"]) / max(1, history["count"])
        dimensions["effectiveness_score"] = _clamp01(dimensions["effectiveness_score"] + delta)
        dimensions["review_pass_score"] = _clamp01(dimensions["review_pass_score"] + delta / 2)
    if usage:
        avg_effect = sum(_float(row.get("content", {}).get("effect_score"), 0.0) for row in usage) / max(1, len(usage))
        dimensions["effectiveness_score"] = _clamp01((dimensions["effectiveness_score"] + avg_effect) / 2)
    if payload.get("reader_feedback_delta") is not None:
        dimensions["reader_feedback_score"] = _clamp01(dimensions["reader_feedback_score"] + _float(payload.get("reader_feedback_delta"), 0.0))
    overall = _overall_quality_score(dimensions)
    content["quality_dimensions"] = dimensions
    content["overall_quality_score"] = overall
    content["quality_score"] = overall
    data["content"] = content
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    metadata["quality_dimensions"] = dimensions
    metadata["overall_quality_score"] = overall
    metadata["quality_score"] = overall
    data["metadata"] = metadata
    data["updated_at"] = utc_now()
    _ensure_valid(data)
    storage.write_json(path, data)
    updated = storage.read_json(path)
    record_mkaos_mutation(
        storage,
        asset_type="knowledge_card",
        asset_id=knowledge_id,
        mutation_type="quality_recalculate",
        previous_payload=previous,
        new_payload=updated,
        changed_fields=_changed_fields(previous, updated),
        reason=str(payload.get("reason") or "recalculate_quality"),
        actor=str(payload.get("actor") or "mkaos"),
        trace_id=str(payload.get("trace_id") or ""),
    )
    return {"path": _display_path(storage.root, path), "asset": updated, "quality_dimensions": dimensions, "overall_quality_score": overall}


def knowledge_quality_history(storage: LocalStorage, knowledge_ref: str | Path, *, limit: int = 200) -> dict[str, Any]:
    knowledge_id = str(knowledge_ref)
    try:
        _, knowledge = _find_asset(storage, knowledge_ref, asset_type="knowledge_card", categories=["knowledge"])
        knowledge_id = str(knowledge.get("id") or knowledge_id)
    except FileNotFoundError:
        pass
    rows = [row for row in _list_assets(storage, "knowledge", "knowledge_quality_score", limit=limit) if str(row.get("content", {}).get("knowledge_id") or "") == knowledge_id]
    return {"knowledge_id": knowledge_id, "count": len(rows), "items": rows}


def list_low_quality_knowledge(storage: LocalStorage, *, threshold: float = 0.45, project_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    rows = list_knowledge_cards(storage, project_id=project_id, include_deprecated=True, limit=limit)
    return [row for row in rows if _float(row.get("content", {}).get("overall_quality_score", row.get("content", {}).get("quality_score", 0.7)), 0.7) < threshold]


def list_high_copyright_risk_knowledge(storage: LocalStorage, *, threshold: float = 0.7, project_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    rows = list_knowledge_cards(storage, project_id=project_id, include_deprecated=True, limit=limit)
    return [
        row
        for row in rows
        if _float((row.get("content", {}).get("quality_dimensions") or {}).get("copyright_risk_score"), 0.0) >= threshold
        or str(row.get("content", {}).get("risk_level") or row.get("metadata", {}).get("risk_level") or "") in {"high", "critical"}
    ]


def create_knowledge_relation(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    source_id = str(payload.get("source_knowledge_id") or payload.get("source_id") or "").strip()
    target_id = str(payload.get("target_knowledge_id") or payload.get("target_id") or "").strip()
    relation_type = str(payload.get("relation_type") or "supports").strip()
    if relation_type not in RELATION_TYPES:
        raise ValueError(f"relation_type must be one of {', '.join(sorted(RELATION_TYPES))}")
    if not source_id or not target_id:
        raise ValueError("source_knowledge_id and target_knowledge_id are required")
    _, source = _find_asset(storage, source_id, asset_type="knowledge_card", categories=["knowledge"])
    _, target = _find_asset(storage, target_id, asset_type="knowledge_card", categories=["knowledge"])
    project_id = str(payload.get("project_id") or source.get("metadata", {}).get("project_id") or target.get("metadata", {}).get("project_id") or "local-system")
    content = {
        "relation_id": "",
        "source_knowledge_id": str(source.get("id") or source_id),
        "target_knowledge_id": str(target.get("id") or target_id),
        "relation_type": relation_type,
        "strength": _clamp01(_float(payload.get("strength"), 0.7)),
        "confidence": _clamp01(_float(payload.get("confidence"), 0.7)),
        "evidence_refs": _strings(payload.get("evidence_refs")),
        "explanation": str(payload.get("explanation") or ""),
        "created_at": utc_now(),
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
    }
    relation_id = _stable_asset_id("knowledge_relation", content["source_knowledge_id"], relation_type, content["target_knowledge_id"])
    content["relation_id"] = relation_id
    asset = _base_asset(
        "knowledge_relation",
        asset_id=relation_id,
        title=f"{relation_type}: {source.get('title')} -> {target.get('title')}",
        source=content["source_knowledge_id"],
        tags=["mkaos", "knowledge-relation", relation_type],
        content=content,
        metadata={"project_id": project_id, "mkaos": True, "use_in_generation_rag": False},
        references=_dedupe([content["source_knowledge_id"], content["target_knowledge_id"], *content["evidence_refs"]]),
    )
    path = storage.write_asset("knowledge", asset)
    record_mkaos_mutation(storage, asset_type="knowledge_relation", asset_id=relation_id, mutation_type="create", new_payload=asset.to_dict(), reason="create_relation", actor=str(payload.get("actor") or "mkaos"), trace_id=str(payload.get("trace_id") or ""))
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def list_knowledge_relations(storage: LocalStorage, *, knowledge_id: str | None = None, relation_type: str | None = None, project_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    rows = _list_assets(storage, "knowledge", "knowledge_relation", project_id=project_id, limit=limit)
    if knowledge_id:
        rows = [
            row
            for row in rows
            if knowledge_id in {str(row.get("content", {}).get("source_knowledge_id") or ""), str(row.get("content", {}).get("target_knowledge_id") or "")}
        ]
    if relation_type:
        rows = [row for row in rows if str(row.get("content", {}).get("relation_type") or "") == relation_type]
    return rows


def create_cross_discipline_fusion_path(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    selected_ids = _strings(payload.get("selected_knowledge_ids"))
    selected: list[dict[str, Any]] = []
    for knowledge_id in selected_ids:
        try:
            _, row = _find_asset(storage, knowledge_id, asset_type="knowledge_card", categories=["knowledge"])
            selected.append(row)
        except FileNotFoundError:
            continue
    if not selected:
        disciplines = _strings(payload.get("selected_disciplines"))
        cards = list_knowledge_cards(storage, project_id=project_id if project_id != "local-system" else None, limit=100)
        selected = [
            row.get("asset", row)
            for row in cards
            if not disciplines or str(row.get("content", {}).get("discipline") or "") in disciplines
        ][:6]
    content = _fusion_content(project_id, payload, selected)
    if not bool(payload.get("persist", False)):
        return content
    asset = _base_asset(
        "cross_discipline_fusion_path",
        title=f"MKAOS fusion {content['flow']} {content['task_goal'][:32]}",
        source=content["task_goal"] or "mkaos-fusion",
        tags=["mkaos", "cross-discipline-fusion", content["flow"]],
        content=content,
        metadata={"project_id": project_id, "mkaos": True, "use_in_generation_rag": False},
        references=content["source_knowledge_ids"],
    )
    path = storage.write_asset("contexts", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path), **content}


def detect_knowledge_conflicts(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    items = payload.get("knowledge_items") if isinstance(payload.get("knowledge_items"), list) else []
    if not items and payload.get("knowledge_pack_id"):
        pack = get_knowledge_pack(storage, str(payload.get("knowledge_pack_id")))["asset"]
        items = pack.get("content", {}).get("pack_items", [])
    conflicts: list[dict[str, Any]] = []
    reasoning_trace: list[dict[str, Any]] = []
    source_policy = payload.get("source_policy") if isinstance(payload.get("source_policy"), dict) else {}
    by_id = {str(item.get("knowledge_id") or ""): item for item in items if isinstance(item, dict)}
    production = _mkaos_payload_is_production(payload)
    for item in items:
        if not isinstance(item, dict):
            continue
        knowledge_id = str(item.get("knowledge_id") or "")
        risk = _normalize_risk_level(str(item.get("risk_level") or "low"))
        status = _normalize_knowledge_status(str(item.get("status") or "verified"))
        quality_dimensions = item.get("quality_dimensions") if isinstance(item.get("quality_dimensions"), dict) else {}
        if status in DO_NOT_SELECT_STATUSES:
            conflicts.append(_knowledge_conflict("knowledge_invalid", "critical", True, [knowledge_id], f"{knowledge_id} status is {status}", "Remove quarantined/deprecated knowledge from pack."))
        if risk == "critical":
            conflicts.append(_knowledge_conflict("knowledge_vs_source_policy", "critical", True, [knowledge_id], f"{knowledge_id} is critical risk.", "Quarantine or replace the knowledge card."))
        if source_policy.get("exclude_high_risk") and risk in {"high", "critical"}:
            conflicts.append(_knowledge_conflict("knowledge_vs_source_policy", "high", True, [knowledge_id], f"{knowledge_id} violates high-risk source policy.", "Use lower-risk abstract knowledge."))
        if _float(quality_dimensions.get("copyright_risk_score"), 0.0) >= 0.8:
            conflicts.append(_knowledge_conflict("knowledge_vs_source_policy", "critical", True, [knowledge_id], f"{knowledge_id} has high copyright risk score.", "Review abstraction boundary before use."))
    graph_relations = list_knowledge_relations(storage, project_id=project_id if project_id != "local-system" else None, limit=1000)
    for relation in graph_relations:
        content = relation.get("content", {})
        left = str(content.get("source_knowledge_id") or "")
        right = str(content.get("target_knowledge_id") or "")
        relation_type = str(content.get("relation_type") or "")
        if relation_type == "contradicts" and left in by_id and right in by_id:
            conflict = _knowledge_conflict("knowledge_vs_knowledge", "high", True, [left, right], f"{left} contradicts {right}.", "Choose one knowledge path or add a task-specific resolution rule.")
            conflict["graph_evidence"] = {"relation_asset_id": relation.get("id", ""), "relation_type": relation_type, "confidence": content.get("confidence", 0.7)}
            conflicts.append(conflict)
            reasoning_trace.append({"reasoning": "graph_relation", "relation_type": relation_type, "source": left, "target": right, "result": "blocking_conflict"})
        elif relation_type == "forbids" and left in by_id and right in by_id:
            conflict = _knowledge_conflict("knowledge_vs_knowledge", "critical", True, [left, right], f"{left} forbids co-selection with {right}.", "Remove one side or create an explicit resolution rule before production.")
            conflict["graph_evidence"] = {"relation_asset_id": relation.get("id", ""), "relation_type": relation_type, "confidence": content.get("confidence", 0.7)}
            conflicts.append(conflict)
            reasoning_trace.append({"reasoning": "graph_relation", "relation_type": relation_type, "source": left, "target": right, "result": "critical_block"})
        elif relation_type == "requires" and left in by_id and right and right not in by_id:
            conflict = _knowledge_conflict(
                "knowledge_vs_knowledge",
                "high" if production else "medium",
                production,
                [left, right],
                f"{left} requires missing supporting knowledge {right}.",
                "Add the required knowledge to the pack or lower the dependent item priority.",
            )
            conflict["graph_evidence"] = {"relation_asset_id": relation.get("id", ""), "relation_type": relation_type, "confidence": content.get("confidence", 0.7)}
            conflicts.append(conflict)
            reasoning_trace.append({"reasoning": "graph_relation", "relation_type": relation_type, "source": left, "target": right, "result": "missing_required_knowledge"})
    inferred_conflicts = _infer_graph_conflicts(graph_relations, by_id, production=production)
    conflicts.extend(inferred_conflicts)
    if inferred_conflicts:
        reasoning_trace.append({"reasoning": "graph_inference", "conflict_count": len(inferred_conflicts), "result": "inferred_conflicts"})
    platform = str(payload.get("platform") or "")
    task_goal = str(payload.get("task_goal") or "")
    for item in items:
        text = " ".join(str(item.get(key) or "") for key in ["concept_name", "core_explanation", "constraint_text"]).lower()
        if platform == "publishing" and any(term in text for term in ["飞卢", "强爽点", "身份差", "快速打脸"]):
            conflicts.append(_knowledge_conflict("knowledge_vs_platform", "medium", False, [str(item.get("knowledge_id") or "")], "Publishing platform conflicts with high-density fast-payoff template.", "Lower commercial rhythm density for publishing flow."))
        if task_goal and "悬疑" in task_goal and "百科" in text:
            conflicts.append(_knowledge_conflict("knowledge_vs_task_goal", "medium", False, [str(item.get("knowledge_id") or "")], "Task goal needs suspense but knowledge is explanatory.", "Convert to clue, contradiction, or delayed evidence."))
    semantic_conflicts = _semantic_pair_conflicts(items, production=production)
    conflicts.extend(semantic_conflicts)
    if semantic_conflicts:
        reasoning_trace.append({"reasoning": "semantic_rule_inference", "conflict_count": len(semantic_conflicts), "result": "semantic_conflicts"})
    canon_result = payload.get("canon_conflict_result") if isinstance(payload.get("canon_conflict_result"), dict) else {}
    for issue in canon_result.get("issues", []) if isinstance(canon_result.get("issues", []), list) else []:
        conflicts.append(_knowledge_conflict("knowledge_vs_canon", str(issue.get("severity") or "critical"), bool(issue.get("blocking", True)), [], str(issue.get("message") or "Canon conflict."), str(issue.get("fix_suggestion") or "Resolve canon conflict first.")))
    model_judge = _model_judge_conflict_result(payload)
    for conflict in model_judge.get("conflicts", []):
        if not isinstance(conflict, dict):
            continue
        severity = str(conflict.get("severity") or "medium")
        conflict_item = _knowledge_conflict(
            str(conflict.get("conflict_type") or "knowledge_vs_knowledge"),
            severity,
            bool(conflict.get("blocking", severity in {"high", "critical"})),
            _strings(conflict.get("involved_knowledge_ids")),
            str(conflict.get("explanation") or "Model judge reported a semantic knowledge conflict."),
            str(conflict.get("recommendation") or "Route to human review or graph-resolution rule."),
        )
        conflict_item["judge_source"] = "model_judge"
        conflict_item["judge_confidence"] = _float(conflict.get("confidence"), 0.5)
        conflicts.append(conflict_item)
    if model_judge.get("requested"):
        reasoning_trace.append({"reasoning": "model_judge", "status": model_judge.get("status"), "opt_in": model_judge.get("opt_in")})
    report = {
        "conflict_report_id": _stable_asset_id("knowledge_conflict_report", project_id, str(payload.get("flow") or ""), str(len(conflicts)), utc_now()),
        "project_id": project_id,
        "flow": str(payload.get("flow") or ""),
        "conflicts": conflicts,
        "blocking_count": len([item for item in conflicts if item.get("blocking")]),
        "reasoning_mode": "deterministic_graph_first_slice",
        "reasoning_trace": reasoning_trace,
        "model_judge": model_judge,
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
    }
    if bool(payload.get("persist", False)):
        asset = _base_asset("knowledge_conflict_report", asset_id=report["conflict_report_id"], title="MKAOS conflict report", source=project_id, tags=["mkaos", "conflict-report"], content=report, metadata={"project_id": project_id, "mkaos": True, "use_in_generation_rag": False})
        path = storage.write_asset("runs", asset)
        report["path"] = _display_path(storage.root, path)
        report["asset_id"] = asset.id
    return report


def run_semantic_conflict_review(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    envelope = _mkaos_envelope(
        storage,
        payload,
        operation="mkaos.semantic_conflict_review",
        asset_type="semantic_conflict_review_report",
        project_id=project_id,
        task_type=str(payload.get("task_type") or payload.get("flow") or "semantic_conflict_review"),
    )
    base_report = detect_knowledge_conflicts(storage, {**payload, "project_id": project_id, "persist": False})
    items = payload.get("knowledge_items") if isinstance(payload.get("knowledge_items"), list) else []
    if not items and payload.get("knowledge_pack_id"):
        try:
            pack = get_knowledge_pack(storage, str(payload.get("knowledge_pack_id")))["asset"]
            items = pack.get("content", {}).get("pack_items", [])
        except FileNotFoundError:
            items = []
    judgments = _semantic_conflict_judgments(items, payload)
    all_conflicts = [*base_report.get("conflicts", []), *judgments["conflicts"]]
    confidence = _semantic_review_confidence(base_report, judgments, payload)
    requires_model_review = bool(payload.get("require_model_review", False)) or confidence < 0.7 or any(item.get("severity") in {"high", "critical"} for item in all_conflicts)
    model_judge = _model_judge_conflict_result(payload)
    if model_judge.get("status") == "completed":
        requires_model_review = False
    content = {
        "semantic_review_id": _stable_asset_id("semantic_conflict_review", project_id, str(payload.get("flow") or ""), str(len(all_conflicts)), str(confidence)),
        "project_id": project_id,
        "flow": str(payload.get("flow") or ""),
        "reasoning_mode": "graph_plus_deterministic_semantic_first_slice",
        "semantic_dimensions": ["platform_rhythm", "narrative_mode", "evidence_logic", "exposition_mode", "canon_policy", "source_policy"],
        "semantic_judgments": judgments["judgments"],
        "conflicts": all_conflicts,
        "blocking_count": len([item for item in all_conflicts if item.get("blocking")]),
        "confidence": confidence,
        "requires_model_review": requires_model_review,
        "model_judge": model_judge,
        "limitations": [
            "deep semantic understanding still requires opt-in external model judge or stronger graph reasoning",
            "deterministic review is designed to fail closed on clear high-risk patterns, not to replace editorial judgment",
        ],
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
        "created_at": utc_now(),
        "envelope_id": envelope.get("envelope_id", ""),
        "trace_id": envelope.get("trace_id", ""),
    }
    if bool(payload.get("persist", True)):
        asset = _base_asset(
            "semantic_conflict_review_report",
            asset_id=content["semantic_review_id"],
            title="MKAOS semantic conflict review",
            source="mkaos-semantic-conflict-review",
            tags=["mkaos", "semantic-conflict-review", "needs-model-review" if requires_model_review else "reviewed"],
            content=content,
            metadata={"project_id": project_id, "mkaos": True, "use_in_generation_rag": False, **envelope_asset_metadata(envelope)},
            references=_dedupe([str(item.get("knowledge_id") or "") for item in items if isinstance(item, dict)]),
        )
        path = storage.write_asset("runs", asset)
        content["path"] = _display_path(storage.root, path)
        content["asset_id"] = asset.id
    return envelope_response(content, envelope)


def attribute_reader_feedback_to_knowledge(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    feedback_text = str(payload.get("feedback_text") or payload.get("comment") or "")
    project_id = str(payload.get("project_id") or "local-system")
    candidate_ids = _strings(payload.get("candidate_knowledge_ids"))
    tags = _feedback_issue_tags(feedback_text)
    recommendation = _feedback_recommendation(tags)
    if not candidate_ids and payload.get("knowledge_pack_id"):
        try:
            pack = get_knowledge_pack(storage, str(payload.get("knowledge_pack_id")))["asset"]
            candidate_ids = [str(item.get("knowledge_id") or "") for item in pack.get("content", {}).get("pack_items", []) if isinstance(item, dict)]
        except FileNotFoundError:
            candidate_ids = []
    matched = _rank_feedback_candidates(storage, candidate_ids, tags)
    content = {
        "feedback_id": str(payload.get("feedback_id") or make_id("reader_feedback", _hash_text(feedback_text))),
        "artifact_id": str(payload.get("artifact_id") or ""),
        "chapter_id": str(payload.get("chapter_id") or ""),
        "related_agent_run_id": str(payload.get("related_agent_run_id") or ""),
        "related_context_bundle_id": str(payload.get("related_context_bundle_id") or payload.get("context_bundle_id") or ""),
        "related_knowledge_pack_id": str(payload.get("related_knowledge_pack_id") or payload.get("knowledge_pack_id") or ""),
        "candidate_knowledge_ids": candidate_ids,
        "attributions": matched,
        "attribution_score": matched[0]["attribution_score"] if matched else 0.0,
        "sentiment": _feedback_sentiment(feedback_text),
        "issue_tags": tags,
        "recommendation": recommendation if matched else "needs_human_review",
        "needs_human_review": not matched,
        "feedback_text_hash": _hash_text(feedback_text),
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
    }
    asset = _base_asset(
        "knowledge_feedback_attribution",
        title=f"Feedback attribution {content['feedback_id']}",
        source=content["artifact_id"] or project_id,
        tags=["mkaos", "feedback-attribution", content["sentiment"]],
        content=content,
        metadata={"project_id": project_id, "mkaos": True, "use_in_generation_rag": False},
        references=_dedupe([content["artifact_id"], content["related_agent_run_id"], content["related_context_bundle_id"], content["related_knowledge_pack_id"], *candidate_ids]),
    )
    path = storage.write_asset("feedback", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def persist_mkaos_review_issues(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.review_issue.service import persist_issue_candidates

    project_id = str(payload.get("project_id") or "local-system")
    target_asset_id = str(payload.get("target_asset_id") or payload.get("artifact_id") or payload.get("knowledge_pack_id") or "unknown-target")
    issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
    candidates = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        issue_type = _mkaos_issue_type(issue)
        severity = str(issue.get("severity") or ("critical" if issue_type in {"source_leakage", "canon_conflict"} else "high"))
        candidates.append(
            {
                **issue,
                "issue_type": issue_type,
                "severity": severity,
                "blocking": bool(issue.get("blocking", severity == "critical" or issue_type in {"source_leakage", "canon_conflict", "mkaos_conflict"})),
                "project_id": project_id,
                "target_asset_id": target_asset_id,
                "target_asset_type": str(payload.get("target_asset_type") or "artifact"),
                "source_system": str(issue.get("source_system") or "mkaos"),
                "evidence_refs": _dedupe([*(_strings(issue.get("evidence_refs"))), *(_strings(payload.get("related_knowledge_ids"))), str(payload.get("knowledge_pack_id") or ""), str(payload.get("context_bundle_id") or "")]),
                "metadata": {
                    "related_knowledge_ids": _strings(payload.get("related_knowledge_ids")) or _strings(issue.get("related_knowledge_ids")),
                    "knowledge_pack_id": str(payload.get("knowledge_pack_id") or issue.get("knowledge_pack_id") or ""),
                    "context_bundle_id": str(payload.get("context_bundle_id") or issue.get("context_bundle_id") or ""),
                },
            }
        )
    return persist_issue_candidates(storage, candidates, source_system="mkaos")


def create_revision_task_from_mkaos_issue(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    issue_ref = str(payload.get("review_issue_id") or payload.get("issue_id") or "")
    issue_content = payload.get("issue") if isinstance(payload.get("issue"), dict) else {}
    if issue_ref:
        try:
            _, issue_asset = _find_asset(storage, issue_ref, asset_type="review_issue", categories=["reviews"])
            issue_content = issue_asset.get("content", {}) if isinstance(issue_asset.get("content", {}), dict) else issue_asset
        except FileNotFoundError:
            pass
    related_knowledge = _strings(payload.get("related_knowledge_ids")) or _strings(issue_content.get("metadata", {}).get("related_knowledge_ids") if isinstance(issue_content.get("metadata"), dict) else None)
    issue_type = str(issue_content.get("issue_type") or payload.get("issue_type") or "mkaos_conflict")
    blocking = bool(issue_content.get("blocking", payload.get("blocking", issue_type == "source_leakage")))
    task_id = _stable_asset_id("revision_task", str(issue_content.get("issue_id") or issue_ref), str(payload.get("artifact_id") or issue_content.get("target_asset_id") or ""))
    content = {
        "task_id": task_id,
        "review_path": str(payload.get("review_path") or issue_content.get("review_report_path") or f"mkaos://review-issue/{issue_ref or task_id}"),
        "source_draft_path": str(payload.get("source_draft_path") or issue_content.get("target_asset_path") or f"mkaos://artifact/{payload.get('artifact_id') or issue_content.get('target_asset_id') or task_id}"),
        "issue_indexes": [0],
        "issues": [issue_content or payload],
        "status": "open",
        "created_at": utc_now(),
        "issue_summary": str(issue_content.get("message") or payload.get("issue_summary") or "MKAOS issue requires revision."),
        "related_knowledge": related_knowledge,
        "knowledge_pack_id": str(payload.get("knowledge_pack_id") or issue_content.get("metadata", {}).get("knowledge_pack_id", "") if isinstance(issue_content.get("metadata"), dict) else ""),
        "context_bundle_id": str(payload.get("context_bundle_id") or ""),
        "revision_instruction": _revision_instruction_for_issue(issue_type),
        "forbidden_changes": _revision_forbidden_changes(issue_type),
        "required_checks": ["source_isolation", "mkaos_review_issue_resolved", "re_review_required"],
        "re_review_criteria": ["blocking issue resolved", "no raw source expression", "knowledge converted to action/conflict/scene"],
        "blocking": blocking,
    }
    asset = _base_asset(
        "revision_task",
        asset_id=task_id,
        title=f"MKAOS revision task {issue_type}",
        source=str(issue_content.get("target_asset_id") or payload.get("artifact_id") or ""),
        tags=["mkaos", "revision-task", issue_type, "blocking" if blocking else "nonblocking"],
        content=content,
        metadata={"project_id": str(payload.get("project_id") or issue_content.get("project_id") or "local-system"), "mkaos": True, "blocking": blocking},
        references=_dedupe([issue_ref, *related_knowledge, content["knowledge_pack_id"], content["context_bundle_id"]]),
    )
    _ensure_valid(asset.to_dict())
    path = storage.write_asset("reviews", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def query_lineage_audit(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    knowledge_id = str(payload.get("knowledge_id") or payload.get("knowledge_ref") or "")
    source_document_id = str(payload.get("source_document_id") or "")
    review_issue_id = str(payload.get("review_issue_id") or "")
    report = _lineage_report(storage, project_id=project_id, knowledge_id=knowledge_id, source_document_id=source_document_id, review_issue_id=review_issue_id)
    if bool(payload.get("persist", True)):
        asset = _base_asset(
            "knowledge_lineage_report",
            asset_id=report["lineage_report_id"],
            title="MKAOS lineage report",
            source=knowledge_id or source_document_id or review_issue_id or project_id,
            tags=["mkaos", "lineage-report"],
            content=report,
            metadata={"project_id": project_id, "mkaos": True, "use_in_generation_rag": False},
            references=report["references"],
        )
        path = storage.write_asset("runs", asset)
        report["path"] = _display_path(storage.root, path)
        report["asset_id"] = asset.id
    return report


def list_mkaos_mutations(storage: LocalStorage, *, asset_id: str | None = None, asset_type: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    rows = _list_assets(storage, "runs", "knowledge_mutation_audit", limit=limit)
    if asset_id:
        rows = [row for row in rows if str(row.get("content", {}).get("asset_id") or "") == asset_id]
    if asset_type:
        rows = [row for row in rows if str(row.get("content", {}).get("asset_type") or "") == asset_type]
    return rows


def list_knowledge_versions(storage: LocalStorage, asset_ref: str | Path, *, limit: int = 100) -> list[dict[str, Any]]:
    asset_id = str(asset_ref)
    try:
        _, data = _find_asset(storage, asset_ref, categories=["knowledge", "contexts", "quality_standards", "templates"])
        asset_id = str(data.get("id") or asset_id)
    except FileNotFoundError:
        pass
    rows = [row for row in _list_assets(storage, "knowledge", "knowledge_version", limit=limit) if str(row.get("content", {}).get("asset_id") or "") == asset_id]
    return sorted(rows, key=lambda row: str(row.get("content", {}).get("created_at") or ""))


def diff_knowledge_versions(storage: LocalStorage, left_ref: str, right_ref: str) -> dict[str, Any]:
    left = _find_version_asset(storage, left_ref)
    right = _find_version_asset(storage, right_ref)
    left_snapshot = left.get("content", {}).get("snapshot", {}) if isinstance(left.get("content", {}), dict) else {}
    right_snapshot = right.get("content", {}).get("snapshot", {}) if isinstance(right.get("content", {}), dict) else {}
    return {
        "left_version_id": left.get("id", ""),
        "right_version_id": right.get("id", ""),
        "changed_fields": _changed_fields(left_snapshot, right_snapshot),
        "left_hash": left.get("content", {}).get("new_content_hash", ""),
        "right_hash": right.get("content", {}).get("new_content_hash", ""),
    }


def rollback_knowledge_version(storage: LocalStorage, version_ref: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    version = _find_version_asset(storage, version_ref)
    content = version.get("content", {}) if isinstance(version.get("content", {}), dict) else {}
    snapshot = content.get("snapshot", {}) if isinstance(content.get("snapshot", {}), dict) else {}
    asset_id = str(content.get("asset_id") or snapshot.get("id") or "")
    if not asset_id or not snapshot:
        raise ValueError("version snapshot is missing")
    path, current = _find_asset(storage, asset_id, asset_type=str(snapshot.get("type") or ""), categories=["knowledge", "contexts", "quality_standards", "templates"])
    previous = json.loads(json.dumps(current, ensure_ascii=False))
    snapshot["updated_at"] = utc_now()
    storage.write_json(path, snapshot)
    record_mkaos_mutation(storage, asset_type=str(snapshot.get("type") or ""), asset_id=asset_id, mutation_type="rollback", previous_payload=previous, new_payload=snapshot, changed_fields=_changed_fields(previous, snapshot), reason=str(payload.get("reason") or "rollback_version"), actor=str(payload.get("actor") or "mkaos"), trace_id=str(payload.get("trace_id") or ""))
    record_knowledge_version(storage, snapshot, previous_payload=previous, reason=str(payload.get("reason") or "rollback"), actor=str(payload.get("actor") or "mkaos"), trace_id=str(payload.get("trace_id") or ""))
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path), "rolled_back_to_version_id": str(version.get("id") or "")}


def pack_debug_report(storage: LocalStorage, pack_ref: str | Path) -> dict[str, Any]:
    pack = get_knowledge_pack(storage, pack_ref)["asset"]
    content = pack.get("content", {}) if isinstance(pack.get("content", {}), dict) else {}
    selector_id = str(content.get("selector_decision_id") or "")
    selector = {}
    if selector_id:
        try:
            _, selector = _find_asset(storage, selector_id, asset_type="selector_decision", categories=["runs", "contexts"])
        except FileNotFoundError:
            selector = {}
    report = {
        "pack_id": str(pack.get("id") or ""),
        "selector_decision_id": selector_id,
        "selected_items": content.get("pack_items", []),
        "rejected_items": content.get("selector_rejections", selector.get("content", {}).get("rejected_knowledge", []) if isinstance(selector.get("content"), dict) else []),
        "score_breakdown": {str(item.get("knowledge_id") or ""): item.get("selector_decision", {}).get("score_breakdown", {}) for item in content.get("pack_items", []) if isinstance(item, dict)},
        "budget_usage": _pack_budget_usage(content),
        "source_isolation_result": content.get("source_isolation", {"raw_text_included": False, "clean_text_included": False}),
        "copyright_risk_result": _copyright_risk_result(content.get("pack_items", [])),
        "quality_score_influence": {str(item.get("knowledge_id") or ""): item.get("selector_decision", {}).get("quality_adjusted_score", item.get("quality_score")) for item in content.get("pack_items", []) if isinstance(item, dict)},
        "feedback_influence": {str(item.get("knowledge_id") or ""): item.get("selector_decision", {}).get("feedback_delta", 0.0) for item in content.get("pack_items", []) if isinstance(item, dict)},
        "platform_match": {str(item.get("knowledge_id") or ""): item.get("selector_decision", {}).get("weight_source", "global") for item in content.get("pack_items", []) if isinstance(item, dict)},
        "genre_match": {str(item.get("knowledge_id") or ""): item.get("selector_decision", {}).get("score_breakdown", {}).get("genre_match_score", 0.0) for item in content.get("pack_items", []) if isinstance(item, dict)},
        "task_goal_match": {str(item.get("knowledge_id") or ""): item.get("selector_decision", {}).get("score_breakdown", {}).get("task_goal_relevance_score", 0.0) for item in content.get("pack_items", []) if isinstance(item, dict)},
        "selector_policy_version": content.get("selector_policy", {}).get("selector_policy_version", "selector-v1"),
        "warnings": content.get("warnings", []),
        "blocking_risks": [item for item in content.get("knowledge_conflicts", []) if isinstance(item, dict) and item.get("blocking")],
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
    }
    asset = _base_asset("pack_debug_report", title=f"Pack debug {pack.get('id')}", source=str(pack.get("id") or ""), tags=["mkaos", "pack-debug"], content=_strip_source_text_fields(report), metadata={"project_id": str(pack.get("metadata", {}).get("project_id") or "local-system"), "mkaos": True, "use_in_generation_rag": False}, references=[str(pack.get("id") or ""), selector_id])
    path = storage.write_asset("runs", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path), **report}


def import_source_with_pipeline(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    source_kind = str(payload.get("source_kind") or "manual_note")
    policy = _source_kind_policy(source_kind)
    text = str(payload.get("text") or payload.get("content") or "")
    cleaned = clean_source_text(text)
    chunks = split_clean_text(cleaned)
    duplicate_count = _duplicate_chunk_count(storage, chunks)
    report = {
        "source_id": "",
        "source_kind": source_kind,
        "chunk_count": len(chunks),
        "duplicate_count": duplicate_count,
        "cleaning_warnings": [] if cleaned else ["empty_after_cleaning"],
        "copyright_boundary": policy["copyright_boundary"],
        "extraction_candidates": policy["recommended_extraction"],
        "recommended_next_actions": ["review evidence spans", "extract candidates", "approve abstractions"],
        "source_policy": policy,
        "dry_run": bool(payload.get("dry_run", False)),
    }
    if report["dry_run"]:
        return {"import_report": report, "source": None}
    result = import_source_document(storage, {**payload, "rights": {**(payload.get("rights") if isinstance(payload.get("rights"), dict) else {}), "allow_downstream_generation": policy["allow_downstream_generation"], "copyright_boundary": policy["copyright_boundary"]}})
    report["source_id"] = result["asset"]["id"]
    report["chunk_count"] = result["chunk_count"]
    asset = _base_asset("knowledge_import_report", title=f"Import report {result['asset'].get('title')}", source=result["asset"]["id"], tags=["mkaos", "import-report", source_kind], content=report, metadata={"project_id": str(payload.get("project_id") or "local-system"), "mkaos": True, "use_in_generation_rag": False}, references=[result["asset"]["id"]])
    path = storage.write_asset("runs", asset)
    return {"import_report": {**report, "path": _display_path(storage.root, path), "asset_id": asset.id}, "source": result}


def run_professional_book_import(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    """Import a professional book into the evidence layer and create reviewable knowledge assets.

    The run is intentionally conservative: source text remains evidence-only,
    generated knowledge/rule/template outputs are candidates, and activation is
    routed through governance approvals.
    """

    project_id = str(payload.get("project_id") or "local-system")
    title = str(payload.get("title") or payload.get("name") or "Professional Book").strip()
    envelope = _mkaos_envelope(
        storage,
        payload,
        operation="mkaos.professional_book_import_run",
        asset_type="professional_book_import_run",
        project_id=project_id,
        task_type="professional_book_import",
    )
    parsed = _parse_professional_book_input(storage, payload)
    if not parsed["text"].strip():
        raise ValueError("professional book import requires text or a readable file")
    structured_chunks = _section_aware_chunks(parsed["sections"], target_chars=int(payload.get("target_chars", 900) or 900))
    import_result = import_source_document(
        storage,
        {
            **payload,
            "project_id": project_id,
            "title": title,
            "text": parsed["text"],
            "source_kind": "professional_book",
            "rights": {
                **(payload.get("rights") if isinstance(payload.get("rights"), dict) else {}),
                "allow_downstream_generation": False,
                "copyright_boundary": "professional book evidence only; abstract extraction required",
            },
            "os_envelope": payload.get("os_envelope") or payload.get("envelope"),
            "environment": payload.get("environment", ""),
            "bypass_reason": payload.get("bypass_reason", ""),
        },
    )
    source_id = str(import_result["asset"].get("id") or "")
    section_chunks = _replace_source_chunks_with_sections(storage, source_id, structured_chunks)
    spans = _create_spans_for_structured_chunks(storage, section_chunks, project_id)
    extraction = _run_professional_book_batch_extraction(storage, project_id, section_chunks, spans, payload)
    rule_candidates = _generate_professional_book_rule_candidates(storage, project_id, extraction["knowledge_candidates"], payload)
    template_candidates = _generate_professional_book_template_candidates(storage, project_id, extraction["knowledge_candidates"], payload)
    approval_queue = _create_professional_book_approval_queue(storage, project_id, extraction["knowledge_candidates"], rule_candidates, template_candidates, payload)
    relation_report = _auto_link_professional_book_relations(storage, project_id, extraction["knowledge_candidates"], rule_candidates, template_candidates, payload)
    graph = _response_data(build_knowledge_graph_explorer(storage, {"project_id": project_id, "persist": bool(payload.get("persist_graph", True))}))
    content = {
        "import_run_id": _stable_asset_id("professional_book_import_run", project_id, title, source_id, str(len(section_chunks))),
        "project_id": project_id,
        "title": title,
        "source_document_id": source_id,
        "parser_report": parsed["parser_report"],
        "section_count": len(parsed["sections"]),
        "chunk_count": len(section_chunks),
        "evidence_span_count": len(spans),
        "extraction_run": extraction["extraction_run"],
        "candidate_counts": {
            "knowledge_card_candidate": len(extraction["knowledge_candidates"]),
            "rule_card_candidate": len(rule_candidates),
            "template_card_candidate": len(template_candidates),
        },
        "approval_queue": approval_queue,
        "relation_report": relation_report,
        "graph_explorer": {
            "explorer_report_id": graph.get("explorer_report_id", ""),
            "summary": graph.get("summary", {}),
            "cluster_count": len(graph.get("clusters", [])),
        },
        "source_policy": _source_kind_policy("professional_book"),
        "source_isolation": {"raw_text_included": False, "clean_text_included": False, "evidence_layer_only": True},
        "created_at": utc_now(),
        "envelope_id": envelope.get("envelope_id", ""),
        "trace_id": envelope.get("trace_id", ""),
    }
    asset = _base_asset(
        "professional_book_import_run",
        asset_id=content["import_run_id"],
        title=f"Professional book import {title}",
        source=source_id,
        tags=["mkaos", "professional-book-import", "book-import-run"],
        content=content,
        metadata={"project_id": project_id, "mkaos": True, "use_in_generation_rag": False, **envelope_asset_metadata(envelope)},
        references=_dedupe(
            [
                source_id,
                *[str(row.get("id") or "") for row in section_chunks],
                *[str(row.get("asset", {}).get("id") or "") for row in spans],
                *[str(item.get("asset", {}).get("id") or "") for item in extraction["knowledge_candidates"]],
                *[str(item.get("candidate_id") or "") for item in rule_candidates],
                *[str(item.get("candidate_id") or "") for item in template_candidates],
            ]
        ),
    )
    path = storage.write_asset("runs", asset)
    content["path"] = _display_path(storage.root, path)
    content["asset_id"] = asset.id
    return envelope_response(content, envelope)


def extract_knowledge_candidates(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    source_chunk_ids = _strings(payload.get("source_chunk_ids"))
    if not source_chunk_ids and payload.get("source_document_id"):
        source_chunk_ids = [row["id"] for row in list_source_chunks(storage, str(payload.get("source_document_id")), limit=20)]
    provider_mode = str(payload.get("provider_mode") or ("model_assisted" if payload.get("provider") or payload.get("mock_provider_candidates") else "local_deterministic"))
    provider_opt_in = _provider_extraction_opted_in(payload)
    provider_candidates = payload.get("mock_provider_candidates") if isinstance(payload.get("mock_provider_candidates"), list) else []
    provider_status = "not_requested"
    provider_warnings: list[str] = []
    if provider_mode == "model_assisted":
        if provider_opt_in:
            provider_status = "mock_provider_ready" if provider_candidates else "provider_opted_in_no_candidates"
        else:
            provider_status = "opt_in_required"
            provider_warnings.append("model-assisted extraction is disabled until NOVEL_FORGE_MKAOS_EXTRACTION_PROVIDER=1 or provider_opt_in=true")
            provider_candidates = []
            provider_mode = "local_deterministic"
    candidates = []
    for index, chunk_id in enumerate(source_chunk_ids[: int(payload.get("limit", 3) or 3)]):
        _, chunk = _find_asset(storage, chunk_id, asset_type="source_chunk", categories=["raw"])
        content = chunk.get("content", {}) if isinstance(chunk.get("content", {}), dict) else {}
        span = create_evidence_span(storage, chunk_id, {"project_id": payload.get("project_id"), "extraction_method": "deterministic"})
        provider_candidate = provider_candidates[index] if index < len(provider_candidates) and isinstance(provider_candidates[index], dict) else {}
        concept = str(provider_candidate.get("concept_name") or payload.get("extraction_goal") or payload.get("concept_name") or f"抽象知识候选 {index + 1}")
        proposed_explanation = str(provider_candidate.get("core_explanation") or "")
        raw_expression_included = bool(proposed_explanation and _candidate_contains_source_expression(proposed_explanation, content))
        core_explanation = _abstract_chunk_to_principle(str(content.get("clean_text") or ""))
        if proposed_explanation and not raw_expression_included:
            core_explanation = proposed_explanation
        elif raw_expression_included:
            provider_warnings.append(f"candidate {concept} contained source-like expression and was replaced with deterministic abstraction")
        candidate_content = {
            "candidate_id": "",
            "candidate_type": "knowledge_card_candidate",
            "concept_name": concept,
            "core_explanation": core_explanation,
            "target_disciplines": _strings(provider_candidate.get("target_disciplines")) or _strings(payload.get("target_disciplines")),
            "target_flows": _strings(provider_candidate.get("target_flows")) or _strings(payload.get("target_flows")),
            "source_chunk_ids": [chunk_id],
            "evidence_refs": [span["asset"]["id"]],
            "confidence": _float(provider_candidate.get("confidence"), 0.72 if provider_candidate else 0.62),
            "copyright_risk": "high" if raw_expression_included else str(provider_candidate.get("copyright_risk") or "low"),
            "abstraction_check": {"raw_expression_included": raw_expression_included, "passed": not raw_expression_included},
            "status": "needs_review",
            "provider_mode": provider_mode,
            "provider_status": provider_status,
        }
        candidate_id = _stable_asset_id("knowledge_card_candidate", chunk_id, concept)
        candidate_content["candidate_id"] = candidate_id
        asset = _base_asset("knowledge_card_candidate", asset_id=candidate_id, title=concept, source=chunk_id, tags=["mkaos", "knowledge-candidate", "needs-review", provider_mode], content=candidate_content, metadata={"project_id": str(payload.get("project_id") or chunk.get("metadata", {}).get("project_id") or "local-system"), "mkaos": True, "asset_status": "needs_review", "use_in_generation_rag": False, "provider_mode": provider_mode, "provider_status": provider_status}, references=[chunk_id, span["asset"]["id"]])
        path = storage.write_asset("knowledge", asset)
        candidates.append({"path": _display_path(storage.root, path), "asset": storage.read_json(path)})
    provider_quality = {}
    if provider_mode == "model_assisted" or provider_status.startswith("mock_provider") or provider_status == "provider_opted_in_no_candidates":
        provider_quality = _response_data(
            validate_extraction_provider_quality(
                storage,
                {
                    **payload,
                    "provider_mode": provider_mode,
                    "provider_status": provider_status,
                    "source_chunk_ids": source_chunk_ids,
                    "candidates": [item["asset"]["content"] for item in candidates],
                    "persist": bool(payload.get("persist_provider_quality", True)),
                },
            )
        )
        if provider_quality and not provider_quality.get("passed", False):
            provider_status = "quality_failed" if provider_opt_in else provider_status
    return {
        "candidates": candidates,
        "candidate_count": len(candidates),
        "provider": {"mode": provider_mode, "status": provider_status, "opt_in": provider_opt_in, "warnings": _dedupe(provider_warnings), "quality_report": provider_quality},
        "warnings": _dedupe(provider_warnings),
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
    }


def validate_extraction_provider_quality(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    envelope = _mkaos_envelope(
        storage,
        payload,
        operation="mkaos.extraction_provider_quality",
        asset_type="knowledge_extraction_provider_quality_report",
        project_id=project_id,
        task_type=str(payload.get("task_type") or "extraction_provider_quality"),
    )
    candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
    candidate_refs = _strings(payload.get("candidate_refs"))
    for ref in candidate_refs:
        try:
            _, candidate = _find_asset(storage, ref, asset_type="knowledge_card_candidate", categories=["knowledge"])
            content = candidate.get("content", {}) if isinstance(candidate.get("content"), dict) else {}
            candidates.append(content)
        except FileNotFoundError:
            continue
    source_chunks = []
    for chunk_id in _strings(payload.get("source_chunk_ids")):
        try:
            _, chunk = _find_asset(storage, chunk_id, asset_type="source_chunk", categories=["raw"])
            source_chunks.append(chunk.get("content", {}) if isinstance(chunk.get("content"), dict) else {})
        except FileNotFoundError:
            continue
    reports = [_provider_candidate_quality(candidate, source_chunks) for candidate in candidates if isinstance(candidate, dict)]
    avg_score = round(sum(item["quality_score"] for item in reports) / max(1, len(reports)), 4)
    threshold = _float(payload.get("quality_threshold"), 0.72)
    issues = [issue for report in reports for issue in report["issues"]]
    opt_in = _provider_extraction_opted_in(payload)
    if not opt_in and str(payload.get("provider_mode") or "") == "model_assisted":
        issues.append({"issue_type": "provider_opt_in_required", "severity": "high", "message": "model-assisted extraction requires explicit provider opt-in"})
    content = {
        "quality_report_id": _stable_asset_id("knowledge_extraction_provider_quality", project_id, str(payload.get("provider_mode") or ""), str(len(reports)), str(len(issues))),
        "project_id": project_id,
        "provider_mode": str(payload.get("provider_mode") or "local_deterministic"),
        "provider_status": str(payload.get("provider_status") or ""),
        "provider": str(payload.get("provider_name") or payload.get("model") or "mock_or_local"),
        "opt_in": opt_in,
        "candidate_count": len(reports),
        "average_quality_score": avg_score,
        "quality_threshold": threshold,
        "passed": bool(reports) and avg_score >= threshold and not any(issue["severity"] in {"high", "critical"} for issue in issues),
        "candidate_reports": reports,
        "issues": issues,
        "recommendations": _provider_quality_recommendations(issues, avg_score, threshold),
        "source_isolation": {"raw_text_included": False, "clean_text_included": False, "source_chunks_checked_by_hash_only": True},
        "created_at": utc_now(),
        "envelope_id": envelope.get("envelope_id", ""),
        "trace_id": envelope.get("trace_id", ""),
    }
    if bool(payload.get("persist", True)):
        asset = _base_asset(
            "knowledge_extraction_provider_quality_report",
            asset_id=content["quality_report_id"],
            title="MKAOS extraction provider quality report",
            source="mkaos-extraction-provider-quality",
            tags=["mkaos", "extraction-provider-quality", content["provider_mode"], "passed" if content["passed"] else "needs-review"],
            content=content,
            metadata={"project_id": project_id, "mkaos": True, "use_in_generation_rag": False, **envelope_asset_metadata(envelope)},
            references=_dedupe([*candidate_refs, *_strings(payload.get("source_chunk_ids"))]),
        )
        path = storage.write_asset("runs", asset)
        content["path"] = _display_path(storage.root, path)
        content["asset_id"] = asset.id
    return envelope_response(content, envelope)


def approve_knowledge_candidate(storage: LocalStorage, candidate_ref: str | Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    _, candidate = _find_asset(storage, candidate_ref, asset_type="knowledge_card_candidate", categories=["knowledge"])
    content = candidate.get("content", {}) if isinstance(candidate.get("content", {}), dict) else {}
    knowledge = create_knowledge_card(
        storage,
        {
            "concept_name": content.get("concept_name"),
            "core_explanation": content.get("core_explanation"),
            "discipline": (_strings(content.get("target_disciplines")) or ["general"])[0],
            "knowledge_type": "mechanism",
            "source_chunk_ids": content.get("source_chunk_ids", []),
            "evidence_span_refs": content.get("evidence_refs", []),
            "status": "verified",
            "project_id": payload.get("project_id") or candidate.get("metadata", {}).get("project_id") or "local-system",
            "actor": payload.get("actor") or "operator",
            "reason": "approve_candidate",
        },
    )
    candidate_path, candidate_data = _find_asset(storage, candidate.get("id", ""), asset_type="knowledge_card_candidate", categories=["knowledge"])
    candidate_content = candidate_data.get("content", {}) if isinstance(candidate_data.get("content", {}), dict) else {}
    candidate_metadata = candidate_data.get("metadata", {}) if isinstance(candidate_data.get("metadata", {}), dict) else {}
    candidate_content["status"] = "approved"
    candidate_metadata["asset_status"] = "approved"
    candidate_metadata["approved_knowledge_id"] = knowledge["asset"]["id"]
    candidate_data["content"] = candidate_content
    candidate_data["metadata"] = candidate_metadata
    candidate_data["updated_at"] = utc_now()
    storage.write_json(candidate_path, candidate_data)
    return {"knowledge": knowledge, "candidate_id": candidate.get("id", "")}


def knowledge_to_application_template(storage: LocalStorage, knowledge_ref: str | Path, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    _, knowledge = _find_asset(storage, knowledge_ref, asset_type="knowledge_card", categories=["knowledge"])
    content = knowledge.get("content", {}) if isinstance(knowledge.get("content", {}), dict) else {}
    flow = str(payload.get("flow") or "outline")
    template = create_template_card(
        storage,
        {
            "template_name": str(payload.get("template_name") or f"{content.get('concept_name', knowledge.get('title'))} {flow} application"),
            "template_type": str(payload.get("template_type") or f"{flow}_template"),
            "structure": payload.get("output_structure") or ["goal", "pressure", "choice", "cost", "payoff"],
            "usage_constraints": ["apply as action/conflict/scene, not exposition", "do not copy source expression"],
            "anti_copy_rules": ["no raw source expression", "no protected scene sequence", "keep source chunks as ids only"],
            "applicable_flows": [flow if flow in MKAOS_FLOWS else "outline"],
            "project_id": payload.get("project_id") or knowledge.get("metadata", {}).get("project_id") or "local-system",
            "metadata": {
                "input_fields": payload.get("input_fields") or ["task_goal", "character_goal", "scene_pressure"],
                "output_structure": payload.get("output_structure") or {"beats": ["pressure", "choice", "cost", "hook"]},
                "application_steps": payload.get("application_steps") or ["identify pressure", "bind to character choice", "show cost", "set hook"],
                "forbidden_usage": payload.get("forbidden_usage") or ["encyclopedia paragraph", "raw source text"],
                "example_placeholder": str(payload.get("example_placeholder") or "<apply abstract mechanism to current project canon>"),
                "success_criteria": payload.get("success_criteria") or ["knowledge changes action", "scene has visible cost", "no raw source text"],
                "risk_checklist": payload.get("risk_checklist") or ["source leakage", "anti-encyclopedia", "canon conflict"],
                "source_knowledge_id": knowledge.get("id", ""),
            },
        },
    )
    return template


def anti_encyclopedia_diagnostics(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    text = _artifact_text(storage, payload)
    issues = _anti_encyclopedia_issues(storage, text)
    suggestions = _dedupe([_rewrite_suggestion_for_issue(issue) for issue in issues] or ["转成人物目标", "转成阻碍", "转成选择代价", "转成章节钩子"])
    if bool(payload.get("persist_review_issue", False)) and issues:
        persist_mkaos_review_issues(storage, {**payload, "issues": issues, "target_asset_id": payload.get("target_asset_id") or payload.get("artifact_id") or "anti-encyclopedia-target"})
    return {"passed": not issues, "issues": issues, "rewrite_suggestions": suggestions, "source_isolation": {"raw_text_included": False, "clean_text_included": False}}


def change_knowledge_status(storage: LocalStorage, knowledge_ref: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    new_status = _normalize_knowledge_status(str(payload.get("status") or payload.get("new_status") or "needs_review"))
    _, previous = _find_asset(storage, knowledge_ref, asset_type="knowledge_card", categories=["knowledge"])
    result = update_knowledge_card(storage, knowledge_ref, {"status": new_status, "reason": payload.get("reason") or "status_change", "actor": payload.get("actor") or "mkaos", "trace_id": payload.get("trace_id") or ""})
    record_mkaos_mutation(
        storage,
        asset_type="knowledge_card",
        asset_id=str(result["asset"].get("id") or ""),
        mutation_type="status_change" if new_status not in {"quarantined", "do_not_select"} else new_status,
        previous_payload=previous,
        new_payload=result["asset"],
        changed_fields=["content.status", "metadata.asset_status"],
        reason=str(payload.get("reason") or "status_change"),
        actor=str(payload.get("actor") or "mkaos"),
        trace_id=str(payload.get("trace_id") or ""),
    )
    return result


def run_knowledge_regression_case(storage: LocalStorage, case_ref_or_payload: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(case_ref_or_payload, dict):
        case = case_ref_or_payload
    else:
        _, asset = _find_asset(storage, case_ref_or_payload, asset_type="knowledge_regression_case", categories=["knowledge", "runs"])
        case = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else asset
    case_type = str(case.get("case_type") or "")
    input_payload = case.get("input_payload") if isinstance(case.get("input_payload"), dict) else {}
    actual: dict[str, Any]
    if case_type == "anti_encyclopedia":
        actual = anti_encyclopedia_diagnostics(storage, input_payload)
    elif case_type == "knowledge_selector":
        actual = build_knowledge_pack(storage, input_payload)
    elif case_type == "knowledge_conflict":
        actual = detect_knowledge_conflicts(storage, input_payload)
    elif case_type == "source_leakage":
        leakage_hit = _contains_source_text_key(input_payload) or bool(input_payload.get("source_leakage_signal"))
        actual = {"passed": not leakage_hit, "issues": [{"issue_type": "source_leakage", "blocking": True}] if leakage_hit else []}
    else:
        actual = validate_artifact(storage, input_payload)
    expected_blocking = bool(case.get("expected_blocking", False))
    actual_blocking = _actual_blocking(actual)
    passed = expected_blocking == actual_blocking
    diff = [] if passed else [f"expected_blocking={expected_blocking} actual_blocking={actual_blocking}"]
    report = {
        "case_id": str(case.get("case_id") or case.get("id") or ""),
        "case_type": case_type,
        "passed": passed,
        "diff": diff,
        "actual_blocking": actual_blocking,
        "actual": _strip_source_text_fields(actual),
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
    }
    return report


def create_knowledge_regression_case(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    case_id = str(payload.get("case_id") or _stable_asset_id("knowledge_regression_case", str(payload.get("case_type") or ""), str(payload.get("title") or utc_now())))
    input_payload = payload.get("input_payload") if isinstance(payload.get("input_payload"), dict) else {}
    if payload.get("project_id") and "project_id" not in input_payload:
        input_payload = {**input_payload, "project_id": payload.get("project_id")}
    content = {
        "case_id": case_id,
        "case_type": str(payload.get("case_type") or "knowledge_selector"),
        "input_payload": input_payload,
        "expected_issues": payload.get("expected_issues") if isinstance(payload.get("expected_issues"), list) else [],
        "expected_blocking": bool(payload.get("expected_blocking", False)),
        "expected_selected_knowledge": _strings(payload.get("expected_selected_knowledge")),
        "expected_rejected_knowledge": _strings(payload.get("expected_rejected_knowledge")),
        "tags": _strings(payload.get("tags")),
        "status": str(payload.get("status") or "active"),
    }
    asset = _base_asset("knowledge_regression_case", asset_id=case_id, title=str(payload.get("title") or f"MKAOS regression {content['case_type']}"), source="mkaos-regression", tags=["mkaos", "regression-case", content["case_type"], *content["tags"]], content=_strip_source_text_fields(content), metadata={"project_id": str(payload.get("project_id") or "local-system"), "mkaos": True, "use_in_generation_rag": False})
    path = storage.write_asset("knowledge", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def run_knowledge_regression_suite(storage: LocalStorage, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    rows = _list_assets(storage, "knowledge", "knowledge_regression_case", project_id=payload.get("project_id"), limit=int(payload.get("limit", 200) or 200))
    if not rows and bool(payload.get("create_default_fixtures", True)):
        for fixture in _default_regression_cases():
            create_knowledge_regression_case(storage, {**fixture, "project_id": payload.get("project_id") or "local-system"})
        rows = _list_assets(storage, "knowledge", "knowledge_regression_case", project_id=payload.get("project_id"), limit=200)
    reports = [run_knowledge_regression_case(storage, row.get("content", {})) for row in rows if str(row.get("content", {}).get("status") or "active") == "active"]
    summary = {"case_count": len(reports), "passed": len([item for item in reports if item["passed"]]), "failed": len([item for item in reports if not item["passed"]])}
    content = {"regression_run_id": _stable_asset_id("knowledge_regression_run", utc_now(), str(summary["case_count"])), "summary": summary, "reports": reports, "source_isolation": {"raw_text_included": False, "clean_text_included": False}}
    asset = _base_asset("knowledge_regression_run_report", asset_id=content["regression_run_id"], title="MKAOS regression suite", source="mkaos-regression", tags=["mkaos", "regression-run"], content=content, metadata={"project_id": str(payload.get("project_id") or "local-system"), "mkaos": True, "use_in_generation_rag": False})
    path = storage.write_asset("runs", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path), **content}


def run_mkaos_acceptance_suite(storage: LocalStorage, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    project_id = str(payload.get("project_id") or "mkaos-p1-acceptance")
    source = import_source_with_pipeline(storage, {"project_id": project_id, "title": "MKAOS P1 acceptance source", "text": "历史制度会改变资源分配；叙事爽点需要选择代价；悬疑证据链需要公平线索。", "source_kind": "manual_note"})
    chunk_id = source["source"]["chunks"][0]["id"]
    span = create_evidence_span(storage, chunk_id, {"project_id": project_id, "chapter_title": "fixture"})
    extraction = extract_knowledge_candidates(storage, {"project_id": project_id, "source_chunk_ids": [chunk_id], "extraction_goal": "制度冲突应用", "target_disciplines": ["历史制度"], "target_flows": ["outline", "prose"]})
    knowledge = approve_knowledge_candidate(storage, extraction["candidates"][0]["asset"]["id"], {"project_id": project_id})["knowledge"]
    knowledge_id = knowledge["asset"]["id"]
    for flow in ["outline", "chapter_outline", "prose", "review", "revision", "recap", "publish", "feedback"]:
        create_usage_binding(storage, knowledge_id, {"flow": flow, "usage_type": "required" if flow != "prose" else "optional", "input_role": "required" if flow != "prose" else "optional", "output_form": "abstract constraint", "constraint_text": "知识必须转化为行动、冲突、代价或审稿检查。", "priority": 10})
    pack = build_knowledge_pack(storage, {"project_id": project_id, "flow": "prose", "task_id": "acceptance-prose", "task_goal": "把制度知识转成场景冲突", "genre": "历史", "platform": "qidian", "environment": "compat", "bypass_reason": "acceptance local fixture"})
    validation = validate_artifact(storage, {"project_id": project_id, "knowledge_pack_id": pack["asset"]["id"], "text": "土地兼并的本质是税源转移。\n\n这种制度导致社会结构变化。"})
    review_issues = persist_mkaos_review_issues(storage, {"project_id": project_id, "target_asset_id": "acceptance-draft", "knowledge_pack_id": pack["asset"]["id"], "context_bundle_id": "acceptance-context", "related_knowledge_ids": [knowledge_id], "issues": validation["issues"]})
    revision_task = create_revision_task_from_mkaos_issue(storage, {"project_id": project_id, "issue": validation["issues"][0] if validation["issues"] else {"issue_type": "mkaos_conflict", "message": "fixture"}, "related_knowledge_ids": [knowledge_id], "artifact_id": "acceptance-draft", "knowledge_pack_id": pack["asset"]["id"], "context_bundle_id": "acceptance-context"})
    feedback = attribute_reader_feedback_to_knowledge(storage, {"project_id": project_id, "feedback_text": "设定太多，节奏慢", "knowledge_pack_id": pack["asset"]["id"], "candidate_knowledge_ids": [knowledge_id]})
    learning = learn_from_knowledge_effects(storage, {"project_id": project_id, "flow": "prose", "persist": True, "apply_updates": False})
    lineage = query_lineage_audit(storage, {"project_id": project_id, "knowledge_id": knowledge_id})
    debug = pack_debug_report(storage, pack["asset"]["id"])
    regression = run_knowledge_regression_suite(storage, {"project_id": project_id, "create_default_fixtures": True})
    content = {
        "project_id": project_id,
        "source_import": source["import_report"],
        "evidence_span_id": span["asset"]["id"],
        "knowledge_id": knowledge_id,
        "knowledge_pack_id": pack["asset"]["id"],
        "validation_issue_count": len(validation["issues"]),
        "review_issue_summary": review_issues,
        "revision_task_id": revision_task["asset"]["id"],
        "feedback_attribution_id": feedback["asset"]["id"],
        "learning_snapshot_id": learning.get("asset_id", ""),
        "lineage_report_id": lineage.get("asset_id", ""),
        "pack_debug_id": debug["asset"]["id"],
        "regression_summary": regression["summary"],
        "passed": bool(pack["asset"]["content"]["pack_items"]) and not _contains_source_text_key(pack["asset"]["content"]),
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
    }
    asset = _base_asset("mkaos_acceptance_report", title="MKAOS P1 knowledge asset OS acceptance", source=project_id, tags=["mkaos", "acceptance"], content=content, metadata={"project_id": project_id, "mkaos": True, "use_in_generation_rag": False}, references=[knowledge_id, pack["asset"]["id"], span["asset"]["id"]])
    path = storage.write_asset("runs", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path), **content}


def _outline_adapter(content: dict[str, Any]) -> dict[str, Any]:
    concepts = _concept_names(content)
    return {
        "flow": "outline",
        "mainline_structure_constraints": _dedupe([item.get("constraint_text", "") for item in content.get("required_knowledge", [])] + ["主线冲突必须体现利益变化"]),
        "stage_conflict_model": concepts,
        "causal_chain_requirements": ["每个制度/知识点必须造成资源、权力或关系后果", "关键转折必须有角色行动触发"],
        "payoff_rhythm": ["压力", "选择", "代价", "局部收益", "下一层风险"],
        "foreshadowing_plan_requirements": ["每卷至少设置一个可回收的证据或物件线索"],
        "villain_interest_logic": ["反派必须有经济、权力或安全动机"],
        "review_rule_refs": [rule.get("rule_id") or rule.get("id") or rule.get("rule_name") for rule in content.get("review_rules", [])],
        "no_prose_segments": True,
    }


def _chapter_outline_adapter(content: dict[str, Any]) -> dict[str, Any]:
    required = content.get("required_knowledge", [])
    return {
        "flow": "chapter_outline",
        "chapter_goal": content.get("current_goal") or "advance chapter conflict through knowledge-backed constraints",
        "scene_list": [
            {
                "goal": "turn knowledge into a visible pressure point",
                "obstacle": item.get("constraint_text") or item.get("core_explanation"),
                "action": "character chooses under cost",
                "result": "resource, relationship, or information state changes",
                "information_change": item.get("concept_name"),
                "emotional_progress": "pressure increases",
                "hook": "new obligation opens",
            }
            for item in required[:5]
        ],
        "action_loop": ["goal", "obstacle", "action", "result", "information_change", "emotional_progress", "hook"],
        "information_release": _dedupe([item.get("output_form", "") for item in required]),
        "foreshadowing_expression": ["use object, record, debt, witness, or delayed payoff"],
        "hook_requirements": ["chapter end must change the next immediate objective"],
        "forbidden_early_reveal": [item.get("concept_name", "") for item in content.get("forbidden_knowledge", [])],
    }


def _prose_adapter(content: dict[str, Any]) -> dict[str, Any]:
    allowed = [*content.get("required_knowledge", []), *content.get("optional_knowledge", [])]
    return {
        "flow": "prose",
        "allowed_knowledge_points": [
            {"knowledge_id": item.get("knowledge_id"), "concept_name": item.get("concept_name"), "allowed_terms": _allowed_terms(item)}
            for item in allowed
        ],
        "action_expression_suggestions": ["let knowledge change what a character does next", "show cost through movement, delay, denial, or physical evidence"],
        "dialogue_expression_suggestions": ["dialogue may reveal pressure, never become a lecture"],
        "object_expression_suggestions": ["use contracts, ledgers, tools, wounds, locations, or props as evidence"],
        "scene_expression_suggestions": ["show the system through queue, office, debt, empty shelves, confiscation, or changed routine"],
        "anti_encyclopedia": {
            "forbidden": ["continuous explanatory paragraphs", "character lecturing for the author", "raw source chunk text"],
            "rewrite_modes": ["action", "dialogue", "object", "scene_change"],
        },
        "knowledge_budget": content.get("knowledge_budget", {}),
        "raw_source_text_included": False,
    }


def _review_adapter(content: dict[str, Any]) -> dict[str, Any]:
    rules = content.get("review_rules", [])
    return {
        "flow": "review",
        "structure_checks": _rule_names(rules, {"logic", "chapter_hook", "knowledge_effectiveness"}),
        "logic_checks": _rule_names(rules, {"logic", "institutional_effectiveness", "interest_conflict"}),
        "character_consistency_checks": _rule_names(rules, {"character_consistency", "interest_conflict"}),
        "canon_checks": _rule_names(rules, {"canon_conflict"}),
        "professional_knowledge_checks": _rule_names(rules, {"knowledge_effectiveness", "institutional_effectiveness"}),
        "platform_risk_checks": ["platform rhythm", "reader promise", "review risk"],
        "anti_encyclopedia_checks": _rule_names(rules, {"anti_encyclopedia"}),
        "issue_contract": ["rule_id", "rule_name", "severity", "blocking", "message", "fix_suggestion", "rollback_level"],
    }


def _base_asset(
    asset_type: str,
    *,
    title: str,
    source: str,
    tags: list[str],
    content: dict[str, Any],
    metadata: dict[str, Any],
    references: list[str] | None = None,
    asset_id: str | None = None,
) -> BaseAsset:
    safe_content = _strip_source_text_fields(content)
    safe_metadata = _strip_source_text_fields(metadata)
    return BaseAsset(
        id=asset_id or _stable_asset_id(asset_type, title, source, utc_now()),
        type=asset_type,
        title=title,
        source=source,
        tags=_dedupe(tags),
        content=safe_content,
        metadata=safe_metadata,
        references=_dedupe(references or []),
    )


def _normalize_knowledge_status(value: str) -> str:
    normalized = str(value or "").strip().lower()
    mapping = {"active": "verified", "disabled": "do_not_select", "blocked": "quarantined"}
    normalized = mapping.get(normalized, normalized)
    return normalized if normalized in KNOWLEDGE_STATUSES else "needs_review"


def _quality_dimensions(payload: Any) -> dict[str, float]:
    source: dict[str, Any] = payload if isinstance(payload, dict) else {}
    nested = source.get("quality_dimensions") if isinstance(source.get("quality_dimensions"), dict) else {}
    result: dict[str, float] = {}
    for key, fallback in QUALITY_DIMENSIONS.items():
        result[key] = _clamp01(_float(nested.get(key, source.get(key, fallback)), fallback))
    if str(source.get("risk_level") or "").strip().lower() in {"high", "critical"}:
        result["copyright_risk_score"] = max(result["copyright_risk_score"], 0.7 if str(source.get("risk_level")).lower() == "high" else 0.9)
    return result


def _overall_quality_score(dimensions: dict[str, Any]) -> float:
    values: list[float] = []
    for key, fallback in QUALITY_DIMENSIONS.items():
        value = _clamp01(_float(dimensions.get(key), fallback))
        values.append(1.0 - value if key == "copyright_risk_score" else value)
    return round(sum(values) / max(1, len(values)), 4)


def _clamp01(value: float) -> float:
    return round(min(1.0, max(0.0, float(value))), 4)


def _changed_fields(previous: dict[str, Any], current: dict[str, Any], prefix: str = "") -> list[str]:
    changed: list[str] = []
    keys = set(previous.keys()) | set(current.keys())
    for key in sorted(keys):
        left = previous.get(key)
        right = current.get(key)
        field = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(left, dict) and isinstance(right, dict):
            changed.extend(_changed_fields(left, right, field))
        elif left != right:
            changed.append(field)
    return changed[:100]


def _term_relevance_score(query: str, fields: list[str]) -> float:
    terms = [term for term in re.split(r"[\s,，。；;:：/]+", str(query or "").lower()) if term]
    if not terms:
        return 0.0
    haystack = " ".join(str(item or "").lower() for item in fields)
    hits = len([term for term in terms if term and term in haystack])
    return round(min(0.35, hits / max(1, len(terms)) * 0.35), 4)


def record_mkaos_mutation(
    storage: LocalStorage,
    *,
    asset_type: str,
    asset_id: str,
    mutation_type: str,
    previous_payload: dict[str, Any] | None = None,
    new_payload: dict[str, Any] | None = None,
    changed_fields: list[str] | None = None,
    reason: str = "",
    actor: str = "mkaos",
    trace_id: str = "",
) -> dict[str, Any]:
    previous_safe = _strip_source_text_fields(previous_payload or {})
    new_safe = _strip_source_text_fields(new_payload or {})
    content = {
        "mutation_id": _stable_asset_id(
            "knowledge_mutation",
            asset_type,
            asset_id,
            mutation_type,
            reason,
            "" if mutation_type == "create" else trace_id or _hash_text(json.dumps(new_safe, ensure_ascii=False, sort_keys=True))[:12],
        ),
        "asset_type": asset_type,
        "asset_id": asset_id,
        "mutation_type": mutation_type,
        "previous_hash": _hash_text(json.dumps(previous_safe, ensure_ascii=False, sort_keys=True)) if previous_payload else "",
        "new_hash": _hash_text(json.dumps(new_safe, ensure_ascii=False, sort_keys=True)) if new_payload else "",
        "changed_fields": changed_fields or _changed_fields(previous_safe, new_safe) if previous_payload and new_payload else changed_fields or [],
        "reason": reason,
        "actor": actor,
        "trace_id": trace_id,
        "created_at": utc_now(),
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
    }
    asset = _base_asset(
        "knowledge_mutation_audit",
        asset_id=content["mutation_id"],
        title=f"{mutation_type} {asset_type} {asset_id}",
        source=asset_id,
        tags=["mkaos", "mutation-audit", mutation_type, asset_type],
        content=content,
        metadata={"project_id": _payload_project_id(new_safe, previous_safe), "mkaos": True, "use_in_generation_rag": False, "trace_id": trace_id},
        references=[asset_id],
    )
    path = storage.write_asset("runs", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def record_knowledge_version(
    storage: LocalStorage,
    payload: dict[str, Any],
    *,
    previous_payload: dict[str, Any] | None = None,
    reason: str = "",
    actor: str = "mkaos",
    trace_id: str = "",
) -> dict[str, Any]:
    safe_payload = _strip_source_text_fields(payload)
    safe_previous = _strip_source_text_fields(previous_payload or {})
    asset_id = str(payload.get("id") or "")
    asset_type = str(payload.get("type") or "knowledge_card")
    content = {
        "version_id": _stable_asset_id(f"{asset_type}_version", asset_id, _hash_text(json.dumps(safe_payload, ensure_ascii=False, sort_keys=True))[:12], utc_now()),
        "asset_id": asset_id,
        "asset_type": asset_type,
        "previous_content_hash": _hash_text(json.dumps(safe_previous, ensure_ascii=False, sort_keys=True)) if previous_payload else "",
        "new_content_hash": _hash_text(json.dumps(safe_payload, ensure_ascii=False, sort_keys=True)),
        "changed_fields": _changed_fields(safe_previous, safe_payload) if previous_payload else list((safe_payload.get("content") or {}).keys())[:100],
        "reason": reason,
        "actor": actor,
        "trace_id": trace_id,
        "created_at": utc_now(),
        "snapshot": safe_payload,
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
    }
    version_type = {
        "knowledge_card": "knowledge_version",
        "rule_card": "rule_version",
        "template_card": "template_version",
        "knowledge_pack": "pack_snapshot_version",
    }.get(asset_type, "knowledge_version")
    asset = _base_asset(
        version_type,
        asset_id=content["version_id"],
        title=f"{asset_type} version {asset_id}",
        source=asset_id,
        tags=["mkaos", "version", asset_type],
        content=content,
        metadata={"project_id": _payload_project_id(safe_payload), "mkaos": True, "use_in_generation_rag": False, "trace_id": trace_id},
        references=[asset_id],
    )
    path = storage.write_asset("knowledge", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _persist_selector_decision(
    storage: LocalStorage,
    *,
    project_id: str,
    flow: str,
    selected_items: list[dict[str, Any]],
    rejected_items: list[dict[str, Any]],
    selector_policy: dict[str, Any],
    budget: dict[str, Any],
    payload: dict[str, Any],
    envelope: dict[str, Any],
) -> dict[str, Any]:
    content = {
        "selector_decision_id": _stable_asset_id("selector_decision", project_id, flow, str(payload.get("task_id") or ""), str(payload.get("chapter_id") or payload.get("chapter") or "")),
        "selector_policy_version": str(selector_policy.get("selector_policy_version") or "selector-v2"),
        "selector_mode": str(selector_policy.get("selector_mode") or "v2"),
        "fallback_reason": str(selector_policy.get("fallback_reason") or ""),
        "selected_knowledge": [
            {
                "knowledge_id": item.get("knowledge_id", ""),
                "concept_name": item.get("concept_name", ""),
                "selection_score": item.get("selection_score", 0.0),
                "score_breakdown": item.get("selector_decision", {}).get("score_breakdown", {}),
                "weight_source": item.get("selector_decision", {}).get("weight_source", "global"),
            }
            for item in selected_items
        ],
        "rejected_knowledge": [
            {
                "knowledge_id": item.get("knowledge_id", ""),
                "concept_name": item.get("concept_name", ""),
                "reason": item.get("reason") or item.get("selector_decision", {}).get("reason", "rejected"),
                "score_breakdown": item.get("score_breakdown", item.get("selector_decision", {})),
            }
            for item in rejected_items
        ],
        "budget_result": _selector_budget_result(selected_items, budget),
        "risk_result": {"high_or_critical": [item.get("knowledge_id", "") for item in selected_items if item.get("risk_level") in {"high", "critical"}]},
        "explanation": f"Selector {selector_policy.get('selector_policy_version', 'selector-v2')} selected {len(selected_items)} item(s), rejected {len(rejected_items)} item(s).",
        "selector_policy": selector_policy,
        "envelope_id": envelope.get("envelope_id", ""),
        "trace_id": envelope.get("trace_id", ""),
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
    }
    asset = _base_asset(
        "selector_decision",
        asset_id=content["selector_decision_id"],
        title=f"MKAOS selector decision {flow}",
        source=str(payload.get("task_id") or flow),
        tags=["mkaos", "selector-decision", flow, content["selector_mode"]],
        content=content,
        metadata={"project_id": project_id, "mkaos": True, "use_in_generation_rag": False, "selector_policy_version": content["selector_policy_version"]},
        references=_dedupe([item.get("knowledge_id", "") for item in selected_items]),
    )
    path = storage.write_asset("runs", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _selector_budget_result(items: list[dict[str, Any]], budget: dict[str, Any]) -> dict[str, Any]:
    estimated = sum(int(item.get("estimated_tokens", 0) or 0) for item in items)
    max_tokens = int(budget.get("max_estimated_tokens") or budget.get("max_selector_tokens") or 0)
    return {
        "selected_count": len(items),
        "estimated_tokens": estimated,
        "max_estimated_tokens": max_tokens,
        "over_budget": bool(max_tokens and estimated > max_tokens),
    }


def _fusion_content(project_id: str, payload: dict[str, Any], selected: list[dict[str, Any]]) -> dict[str, Any]:
    disciplines = _dedupe([str((row.get("content", {}) if isinstance(row.get("content"), dict) else {}).get("discipline") or "") for row in selected])
    names = _dedupe([str((row.get("content", {}) if isinstance(row.get("content"), dict) else {}).get("concept_name") or row.get("title") or "") for row in selected])
    flow = str(payload.get("flow") or "prose")
    task_goal = str(payload.get("task_goal") or payload.get("goal") or "")
    reasoning = [f"{discipline} -> {name}" for discipline, name in zip(disciplines or ["general"], names or ["knowledge"])]
    narrative = "将知识组合成目标、阻碍、选择、代价、结果和钩子，而不是说明性资料。"
    if {"历史制度", "叙事学"} & set(disciplines):
        narrative = "把制度压力转成资源分配和人物利益冲突，再落到章节选择代价。"
    if "哲学" in disciplines:
        narrative = "把哲学命题转成人物不可兼得的选择和弧光推进。"
    if "逻辑学" in disciplines or "悬疑" in str(payload.get("genre") or ""):
        narrative = "把逻辑约束转成公平线索、误导、证据链和可复盘推理。"
    return {
        "fusion_path_id": _stable_asset_id("fusion_path", project_id, flow, task_goal, ",".join(names)),
        "project_id": project_id,
        "task_goal": task_goal,
        "genre": str(payload.get("genre") or ""),
        "platform": str(payload.get("platform") or ""),
        "flow": flow,
        "source_knowledge_ids": [str(row.get("id") or "") for row in selected],
        "reasoning_path": reasoning,
        "narrative_application": narrative,
        "character_application": "绑定到角色目标、动机压力、关系债务或身份代价。",
        "conflict_application": "至少制造一组利益相反的行动方，并让结果改变资源、信息或关系。",
        "scene_application": "优先使用物件、行动、动作、对话、地点状态和证据线索承载知识。",
        "review_rules": ["anti_encyclopedia", "causal_chain", "source_isolation"],
        "forbidden_usage": ["raw source expression", "encyclopedia paragraph", "platform rule as lecture"],
        "risk_warnings": [],
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
    }


def _knowledge_conflict(conflict_type: str, severity: str, blocking: bool, knowledge_ids: list[str], explanation: str, recommendation: str) -> dict[str, Any]:
    return {
        "conflict_id": _stable_asset_id("knowledge_conflict", conflict_type, ",".join(knowledge_ids), explanation),
        "conflict_type": conflict_type,
        "severity": severity if severity in {"low", "medium", "high", "critical"} else "medium",
        "blocking": bool(blocking),
        "involved_knowledge_ids": _dedupe(knowledge_ids),
        "involved_rule_ids": [],
        "involved_platform_profile_ids": [],
        "explanation": explanation,
        "recommendation": recommendation,
    }


def _mkaos_payload_is_production(payload: dict[str, Any]) -> bool:
    envelope = payload.get("os_envelope") if isinstance(payload.get("os_envelope"), dict) else payload.get("envelope") if isinstance(payload.get("envelope"), dict) else {}
    environment = str(payload.get("environment") or envelope.get("environment") or "")
    return is_production_environment(environment) or bool(payload.get("strict", False))


def _model_judge_conflict_result(payload: dict[str, Any]) -> dict[str, Any]:
    requested = bool(payload.get("enable_model_judge") or payload.get("model_judge_enabled") or payload.get("model_judge") or payload.get("model_judge_result"))
    opt_in = bool(payload.get("model_judge_opt_in") or os.environ.get("NOVEL_FORGE_MKAOS_MODEL_JUDGE") == "1")
    if not requested:
        return {"requested": False, "opt_in": False, "status": "not_requested", "conflicts": []}
    if not opt_in:
        return {"requested": True, "opt_in": False, "status": "opt_in_required", "conflicts": [], "provider": str(payload.get("model_judge_provider") or "")}
    judge_payload = payload.get("model_judge_result") if isinstance(payload.get("model_judge_result"), dict) else {}
    conflicts = judge_payload.get("conflicts") if isinstance(judge_payload.get("conflicts"), list) else []
    return {
        "requested": True,
        "opt_in": True,
        "status": "completed" if conflicts else "no_conflict_returned",
        "provider": str(payload.get("model_judge_provider") or judge_payload.get("provider") or "mock"),
        "conflicts": _strip_source_text_fields(conflicts),
    }


def _infer_graph_conflicts(graph_relations: list[dict[str, Any]], selected_by_id: dict[str, dict[str, Any]], *, production: bool) -> list[dict[str, Any]]:
    selected = set(selected_by_id)
    if not selected:
        return []
    supportive_edges: dict[str, set[str]] = {}
    blocking_edges: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for relation in graph_relations:
        content = relation.get("content", {}) if isinstance(relation.get("content"), dict) else {}
        left = str(content.get("source_knowledge_id") or "")
        right = str(content.get("target_knowledge_id") or "")
        relation_type = str(content.get("relation_type") or "")
        if not left or not right:
            continue
        if relation_type in {"supports", "requires", "refines", "generalizes", "specializes", "causes"}:
            supportive_edges.setdefault(left, set()).add(right)
        if relation_type in {"contradicts", "forbids"}:
            blocking_edges.setdefault(left, []).append((right, relation_type, relation))
    conflicts: list[dict[str, Any]] = []
    for source_id in sorted(selected):
        reachable = _reachable_knowledge_ids(source_id, supportive_edges, max_depth=3)
        for intermediate in sorted(reachable):
            for target_id, relation_type, relation in blocking_edges.get(intermediate, []):
                if target_id not in selected or target_id == source_id:
                    continue
                severity = "critical" if relation_type == "forbids" else "high"
                conflict = _knowledge_conflict(
                    "knowledge_vs_knowledge",
                    severity,
                    True if production or severity == "critical" else False,
                    [source_id, intermediate, target_id],
                    f"{source_id} implies {intermediate}, which {relation_type} selected knowledge {target_id}.",
                    "Resolve the inferred graph path or split the pack into separate knowledge paths.",
                )
                conflict["graph_evidence"] = {
                    "inference": "transitive_support_to_blocking_relation",
                    "intermediate_knowledge_id": intermediate,
                    "blocking_relation_type": relation_type,
                    "relation_asset_id": relation.get("id", ""),
                }
                conflicts.append(conflict)
    dedup: dict[str, dict[str, Any]] = {}
    for conflict in conflicts:
        dedup[str(conflict.get("conflict_id") or "")] = conflict
    return list(dedup.values())


def _reachable_knowledge_ids(source_id: str, edges: dict[str, set[str]], *, max_depth: int) -> set[str]:
    visited: set[str] = set()
    frontier = [(source_id, 0)]
    while frontier:
        current, depth = frontier.pop(0)
        if depth >= max_depth:
            continue
        for target in sorted(edges.get(current, set())):
            if target in visited:
                continue
            visited.add(target)
            frontier.append((target, depth + 1))
    return visited


def _semantic_pair_conflicts(items: list[dict[str, Any]], *, production: bool) -> list[dict[str, Any]]:
    rules = [
        {
            "left": {"快节奏", "强情绪", "反转密度", "强爽点", "打脸"},
            "right": {"文学质感", "慢热", "结构完整", "语言稳定", "出版向"},
            "severity": "high",
            "explanation": "Fast-payoff rhythm conflicts with literary/publishing rhythm in the same production pack.",
            "recommendation": "Choose a platform-specific rhythm path before generation.",
        },
        {
            "left": {"百科", "设定详解", "资料卡", "说明性"},
            "right": {"低门槛", "动作化", "强钩子", "番茄"},
            "severity": "medium",
            "explanation": "Expository knowledge conflicts with low-barrier actionized platform strategy.",
            "recommendation": "Convert the knowledge to action, obstacle, scene state, or hook.",
        },
        {
            "left": {"公平线索", "可复盘", "证据链"},
            "right": {"突然反转", "神秘解决", "莫名"},
            "severity": "high",
            "explanation": "Fair clue chain conflicts with arbitrary twist resolution.",
            "recommendation": "Add evidence positions or downgrade the arbitrary twist template.",
        },
    ]
    prepared = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = json.dumps(_strip_source_text_fields(item), ensure_ascii=False)
        prepared.append((str(item.get("knowledge_id") or ""), text))
    conflicts: list[dict[str, Any]] = []
    for index, (left_id, left_text) in enumerate(prepared):
        for right_id, right_text in prepared[index + 1 :]:
            pair_text = f"{left_text}\n{right_text}"
            for rule in rules:
                if any(term in pair_text for term in rule["left"]) and any(term in pair_text for term in rule["right"]):
                    severity = str(rule["severity"])
                    conflicts.append(
                        _knowledge_conflict(
                            "knowledge_vs_task_goal",
                            severity,
                            production and severity in {"high", "critical"},
                            [left_id, right_id],
                            str(rule["explanation"]),
                            str(rule["recommendation"]),
                        )
                    )
                    break
    return conflicts


def _semantic_conflict_judgments(items: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
    judgments: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    profiles: list[dict[str, Any]] = []
    production = _mkaos_payload_is_production(payload)
    for item in items:
        if not isinstance(item, dict):
            continue
        profile = _semantic_item_profile(item)
        profiles.append(profile)
        judgments.append(
            {
                "knowledge_id": profile["knowledge_id"],
                "platform_rhythm": profile["platform_rhythm"],
                "narrative_mode": profile["narrative_mode"],
                "evidence_logic": profile["evidence_logic"],
                "exposition_mode": profile["exposition_mode"],
                "canon_policy": profile["canon_policy"],
                "confidence": profile["confidence"],
            }
        )
    for index, left in enumerate(profiles):
        for right in profiles[index + 1 :]:
            pair_conflicts = _semantic_profile_conflicts(left, right, production=production)
            conflicts.extend(pair_conflicts)
    return {"judgments": judgments, "conflicts": conflicts}


def _semantic_item_profile(item: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(_strip_source_text_fields(item), ensure_ascii=False).lower()
    rhythm = "neutral"
    if any(term in text for term in ["快节奏", "强情绪", "反转", "打脸", "爽点", "番茄", "飞卢"]):
        rhythm = "fast_payoff"
    if any(term in text for term in ["出版", "文学质感", "慢热", "结构完整", "语言稳定"]):
        rhythm = "literary_slow_burn" if rhythm == "neutral" else "mixed"
    narrative_mode = "actionized" if any(term in text for term in ["行动", "冲突", "选择", "代价", "场景", "钩子"]) else "unclear"
    exposition_mode = "expository" if any(term in text for term in ["百科", "资料卡", "说明性", "设定详解", "解释"]) else "abstracted"
    evidence_logic = "fair_clue" if any(term in text for term in ["公平线索", "可复盘", "证据链", "因果"]) else "unspecified"
    if any(term in text for term in ["突然反转", "莫名", "神秘解决", "天降"]):
        evidence_logic = "arbitrary_twist" if evidence_logic == "unspecified" else "mixed"
    canon_policy = "canon_bound" if any(term in text for term in ["canon", "设定事实", "世界规则", "人物状态", "连续性"]) else "unbound"
    positive_signals = len([value for value in [rhythm, narrative_mode, exposition_mode, evidence_logic, canon_policy] if value not in {"neutral", "unclear", "unspecified", "unbound"}])
    return {
        "knowledge_id": str(item.get("knowledge_id") or ""),
        "platform_rhythm": rhythm,
        "narrative_mode": narrative_mode,
        "exposition_mode": exposition_mode,
        "evidence_logic": evidence_logic,
        "canon_policy": canon_policy,
        "confidence": round(min(0.92, 0.42 + positive_signals * 0.12), 4),
    }


def _semantic_profile_conflicts(left: dict[str, Any], right: dict[str, Any], *, production: bool) -> list[dict[str, Any]]:
    left_id = str(left.get("knowledge_id") or "")
    right_id = str(right.get("knowledge_id") or "")
    result: list[dict[str, Any]] = []
    rhythms = {left.get("platform_rhythm"), right.get("platform_rhythm")}
    if {"fast_payoff", "literary_slow_burn"} <= rhythms or "mixed" in rhythms:
        result.append(
            _knowledge_conflict(
                "knowledge_vs_platform",
                "high",
                production,
                [left_id, right_id],
                "Semantic rhythm profile mixes fast-payoff platform logic with literary slow-burn publishing logic.",
                "Choose a platform-specific path or split the pack before production.",
            )
        )
    evidence_modes = {left.get("evidence_logic"), right.get("evidence_logic")}
    if {"fair_clue", "arbitrary_twist"} <= evidence_modes or "mixed" in evidence_modes:
        result.append(
            _knowledge_conflict(
                "knowledge_vs_task_goal",
                "high",
                production,
                [left_id, right_id],
                "Semantic evidence profile mixes fair clue chain with arbitrary twist resolution.",
                "Preserve evidence positions or route the twist through a reviewed clue path.",
            )
        )
    if "expository" in {left.get("exposition_mode"), right.get("exposition_mode")} and "actionized" not in {left.get("narrative_mode"), right.get("narrative_mode")}:
        result.append(
            _knowledge_conflict(
                "knowledge_vs_task_goal",
                "medium",
                False,
                [left_id, right_id],
                "Semantic profile is exposition-heavy without a paired actionized narrative mode.",
                "Add an action/conflict conversion rule before prose use.",
            )
        )
    return result


def _semantic_review_confidence(base_report: dict[str, Any], judgments: dict[str, Any], payload: dict[str, Any]) -> float:
    judgment_rows = judgments.get("judgments") if isinstance(judgments.get("judgments"), list) else []
    if not judgment_rows:
        return 0.0
    avg = sum(_float(item.get("confidence"), 0.0) for item in judgment_rows) / len(judgment_rows)
    if base_report.get("model_judge", {}).get("status") == "completed" or _model_judge_conflict_result(payload).get("status") == "completed":
        avg = max(avg, 0.9)
    if base_report.get("reasoning_trace"):
        avg = min(0.95, avg + 0.08)
    return round(max(0.0, min(1.0, avg)), 4)


def _provider_extraction_opted_in(payload: dict[str, Any]) -> bool:
    provider = payload.get("provider") if isinstance(payload.get("provider"), dict) else {}
    return bool(payload.get("provider_opt_in") or provider.get("opt_in") or os.environ.get("NOVEL_FORGE_MKAOS_EXTRACTION_PROVIDER") == "1")


def _candidate_contains_source_expression(candidate_text: str, source_content: dict[str, Any]) -> bool:
    candidate = re.sub(r"\s+", "", str(candidate_text or ""))
    if len(candidate) < 8:
        return False
    source_text = re.sub(r"\s+", "", str(source_content.get("clean_text") or source_content.get("raw_text") or ""))
    if not source_text:
        return False
    if candidate and candidate in source_text:
        return True
    for size in [24, 18, 12]:
        if len(candidate) >= size:
            for index in range(0, len(candidate) - size + 1, max(1, size // 2)):
                if candidate[index : index + size] in source_text:
                    return True
    return False


def _provider_candidate_quality(candidate: dict[str, Any], source_chunks: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_id = str(candidate.get("candidate_id") or candidate.get("knowledge_id") or "")
    concept = str(candidate.get("concept_name") or "")
    explanation = str(candidate.get("core_explanation") or "")
    issues: list[dict[str, Any]] = []
    score = 1.0
    if not concept:
        issues.append({"issue_type": "missing_concept_name", "severity": "medium", "message": "candidate concept_name is required"})
        score -= 0.15
    if len(explanation.strip()) < 16:
        issues.append({"issue_type": "weak_abstraction", "severity": "medium", "message": "candidate core_explanation is too short to validate transferability"})
        score -= 0.2
    if not _strings(candidate.get("target_flows")):
        issues.append({"issue_type": "missing_target_flows", "severity": "low", "message": "target_flows missing; candidate cannot be bound automatically"})
        score -= 0.08
    if not _strings(candidate.get("target_disciplines")):
        issues.append({"issue_type": "missing_target_disciplines", "severity": "low", "message": "target_disciplines missing; graph classification will be weak"})
        score -= 0.06
    abstraction = candidate.get("abstraction_check") if isinstance(candidate.get("abstraction_check"), dict) else {}
    if abstraction.get("raw_expression_included"):
        issues.append({"issue_type": "source_expression_included", "severity": "critical", "message": "candidate abstraction check detected source-like expression"})
        score -= 0.5
    for source_content in source_chunks:
        if _candidate_contains_source_expression(explanation, source_content):
            issues.append({"issue_type": "source_expression_overlap", "severity": "critical", "message": "candidate overlaps with source expression"})
            score -= 0.5
            break
    confidence = _float(candidate.get("confidence"), 0.5)
    if confidence < 0.55:
        issues.append({"issue_type": "low_provider_confidence", "severity": "medium", "message": "provider confidence below acceptance threshold"})
        score -= 0.12
    if str(candidate.get("copyright_risk") or "").lower() in {"high", "critical"}:
        issues.append({"issue_type": "copyright_risk", "severity": "high", "message": "candidate copyright risk is too high for automatic promotion"})
        score -= 0.25
    return {
        "candidate_id": candidate_id,
        "concept_name": concept,
        "quality_score": _clamp01(score),
        "confidence": confidence,
        "passed": score >= 0.72 and not any(issue["severity"] in {"high", "critical"} for issue in issues),
        "issues": issues,
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
    }


def _provider_quality_recommendations(issues: list[dict[str, Any]], avg_score: float, threshold: float) -> list[str]:
    if not issues and avg_score >= threshold:
        return ["provider candidates are eligible for human review or guarded approval"]
    recommendations = []
    issue_types = {str(issue.get("issue_type") or "") for issue in issues}
    if {"source_expression_included", "source_expression_overlap"} & issue_types:
        recommendations.append("reject source-like candidate text and rerun abstraction")
    if "provider_opt_in_required" in issue_types:
        recommendations.append("enable provider only through explicit Runtime Policy opt-in")
    if {"missing_target_flows", "missing_target_disciplines"} & issue_types:
        recommendations.append("require provider output to include flow and discipline classification")
    if avg_score < threshold:
        recommendations.append("keep candidates in needs_review until quality score improves")
    return _dedupe(recommendations)


def _mkaos_envelope(
    storage: LocalStorage,
    payload: dict[str, Any],
    *,
    operation: str,
    asset_type: str,
    project_id: str,
    task_type: str,
    token_budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    envelope_payload = payload.get("os_envelope") if isinstance(payload.get("os_envelope"), dict) else payload.get("envelope") if isinstance(payload.get("envelope"), dict) else None
    source_policy = payload.get("source_policy") if isinstance(payload.get("source_policy"), dict) else {
        "raw_source_text_allowed": False,
        "generation_rag_allowed": False,
        "source_chunk_raw_text_allowed": False,
    }
    return enforce_os_envelope(
        storage,
        envelope_payload=envelope_payload,
        operation=operation,
        project_id=project_id,
        task_type=str(payload.get("task_type") or task_type or operation),
        asset_type=asset_type,
        actor_type=str(payload.get("actor_type") or "mkaos_service"),
        actor_id=str(payload.get("actor_id") or ""),
        source="mkaos",
        context_bundle_id=str(payload.get("context_bundle_id") or ""),
        trace_id=str(payload.get("trace_id") or ""),
        provider=str(payload.get("provider") or ""),
        model=str(payload.get("model") or ""),
        token_budget=token_budget,
        source_policy=source_policy,
        environment=str(payload.get("environment") or ""),
        bypass_reason=str(payload.get("bypass_reason") or ""),
    )


def _knowledge_matches_terms(row: dict[str, Any], terms: list[str]) -> bool:
    if not terms:
        return True
    haystack = json.dumps(
        {
            "title": row.get("title", ""),
            "tags": row.get("tags", []),
            "content": row.get("content", {}),
        },
        ensure_ascii=False,
    ).lower()
    return all(term in haystack for term in terms)


def _query_row(row: dict[str, Any], bindings: list[dict[str, Any]]) -> dict[str, Any]:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    metadata = row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}
    quality = _float(content.get("quality_score", metadata.get("quality_score", 0.7)), 0.7)
    weight = _float(content.get("weight", metadata.get("weight", 1.0)), 1.0)
    priority_bonus = 0.0
    if bindings:
        best_priority = min(int(binding.get("content", {}).get("priority", 100) or 100) for binding in bindings)
        priority_bonus = max(0.0, (100 - best_priority) / 100)
    return {
        "id": row.get("id", ""),
        "path": row.get("path", ""),
        "title": row.get("title", ""),
        "concept_name": content.get("concept_name", row.get("title", "")),
        "discipline": content.get("discipline", ""),
        "knowledge_type": content.get("knowledge_type", ""),
        "status": content.get("status", metadata.get("asset_status", "")),
        "risk_level": content.get("risk_level", metadata.get("risk_level", "")),
        "quality_score": quality,
        "weight": weight,
        "binding_count": len(bindings),
        "selection_score": round((quality * weight) + priority_bonus, 4),
        "source_chunk_ids": content.get("source_chunk_ids", []),
    }


def _knowledge_graph_content(
    storage: LocalStorage,
    *,
    project_id: str,
    flow: str = "",
    discipline: str = "",
    include_deprecated: bool = False,
    limit: int = 500,
) -> dict[str, Any]:
    project_filter = project_id if project_id != "local-system" else None
    valid_flow = flow if flow in MKAOS_FLOWS else ""
    knowledge_rows = list_knowledge_cards(storage, project_id=project_filter, include_deprecated=include_deprecated, limit=limit)
    if discipline:
        needle = discipline.strip().lower()
        knowledge_rows = [row for row in knowledge_rows if needle in str(row.get("content", {}).get("discipline", "")).lower()]
    knowledge_ids = {str(row.get("id") or "") for row in knowledge_rows}
    bindings = [
        row
        for row in list_usage_bindings(storage, flow=valid_flow or None, enabled=True, limit=2000)
        if str(row.get("content", {}).get("knowledge_id") or "") in knowledge_ids
        and _project_scope_matches(str(row.get("metadata", {}).get("project_id") or ""), project_id)
    ]
    usage_events = list_usage_events(storage, project_id=project_filter, flow=valid_flow or None, limit=3000)
    quality_scores = _list_quality_scores(storage, project_id=project_filter, flow=valid_flow or None, limit=3000)
    rule_rows = [
        row
        for row in list_rule_cards(storage, flow=valid_flow or None, enabled=True, limit=500)
        if _project_scope_matches(str(row.get("metadata", {}).get("project_id") or ""), project_id)
    ]
    template_rows = [
        row
        for row in list_template_cards(storage, flow=valid_flow or None, enabled=True, limit=500)
        if _project_scope_matches(str(row.get("metadata", {}).get("project_id") or ""), project_id)
    ]
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    def add_node(node: dict[str, Any]) -> None:
        nodes[str(node["id"])] = node

    def add_edge(source: str, target: str, relation: str, **attrs: Any) -> None:
        if source not in nodes or target not in nodes:
            return
        edge_id = _stable_asset_id("mkaos_edge", source, relation, target)
        edges[edge_id] = {
            "id": edge_id,
            "source": source,
            "target": target,
            "relation": relation,
            "attributes": _safe_graph_attrs(attrs),
        }

    for flow_name in sorted(MKAOS_FLOWS):
        if valid_flow and flow_name != valid_flow:
            continue
        add_node({"id": f"flow:{flow_name}", "node_type": "flow", "label": flow_name, "attributes": {"flow": flow_name}})

    for row in knowledge_rows:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        metadata = row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}
        knowledge_id = str(row.get("id") or "")
        node_id = f"knowledge:{knowledge_id}"
        knowledge_flow = valid_flow or _first_knowledge_flow(knowledge_id, bindings, usage_events, quality_scores)
        metrics = _knowledge_learning_metrics(knowledge_id, usage_events, quality_scores, knowledge_flow)
        add_node(
            {
                "id": node_id,
                "node_type": "knowledge_card",
                "asset_id": knowledge_id,
                "path": row.get("path", ""),
                "label": str(content.get("concept_name") or row.get("title") or knowledge_id),
                "attributes": _safe_graph_attrs(
                    {
                        "project_id": metadata.get("project_id") or content.get("project_id") or project_id,
                        "discipline": content.get("discipline", ""),
                        "sub_discipline": content.get("sub_discipline", ""),
                        "knowledge_type": content.get("knowledge_type", ""),
                        "status": content.get("status", metadata.get("asset_status", "")),
                        "risk_level": content.get("risk_level", metadata.get("risk_level", "")),
                        "quality_score": _float(content.get("quality_score", metadata.get("quality_score", 0.7)), 0.7),
                        "weight": _float(content.get("weight", metadata.get("weight", 1.0)), 1.0),
                        "confidence": _float(content.get("confidence"), 0.7),
                        "source_chunk_ids": content.get("source_chunk_ids", []),
                        "usage_count": metrics["usage_count"],
                        "observed_effect_count": metrics["observed_effect_count"],
                        "avg_effect_score": metrics["avg_effect_score"],
                        "feedback_delta": metrics["feedback_delta"],
                    }
                ),
            }
        )
        discipline_name = str(content.get("discipline") or "general").strip() or "general"
        discipline_id = f"discipline:{discipline_name}"
        add_node({"id": discipline_id, "node_type": "discipline", "label": discipline_name, "attributes": {"discipline": discipline_name}})
        add_edge(node_id, discipline_id, "classified_as")
        for chunk_id in _strings(content.get("source_chunk_ids")):
            chunk_node = _source_chunk_graph_node(storage, chunk_id)
            if chunk_node:
                add_node(chunk_node)
                add_edge(chunk_node["id"], node_id, "evidence_for", evidence_ref=chunk_id)

    rule_by_id: dict[str, dict[str, Any]] = {}
    for row in rule_rows:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        node_id = f"rule:{row.get('id')}"
        rule_by_id[str(row.get("id") or "")] = row
        add_node(
            {
                "id": node_id,
                "node_type": "rule_card",
                "asset_id": row.get("id", ""),
                "path": row.get("path", ""),
                "label": str(content.get("rule_name") or row.get("title") or row.get("id")),
                "attributes": _safe_graph_attrs(
                    {
                        "rule_type": content.get("rule_type", ""),
                        "severity": content.get("severity", ""),
                        "blocking": bool(content.get("blocking", False)),
                        "applicable_flows": content.get("applicable_flows", []),
                    }
                ),
            }
        )
        for flow_name in _strings(content.get("applicable_flows")):
            if valid_flow and flow_name != valid_flow:
                continue
            add_edge(f"flow:{flow_name}", node_id, "governed_by_rule", severity=content.get("severity", ""))

    template_by_id: dict[str, dict[str, Any]] = {}
    for row in template_rows:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        node_id = f"template:{row.get('id')}"
        template_by_id[str(row.get("id") or "")] = row
        add_node(
            {
                "id": node_id,
                "node_type": "template_card",
                "asset_id": row.get("id", ""),
                "path": row.get("path", ""),
                "label": str(content.get("template_name") or row.get("title") or row.get("id")),
                "attributes": _safe_graph_attrs(
                    {
                        "template_type": content.get("template_type", ""),
                        "applicable_flows": content.get("applicable_flows", []),
                        "usage_constraints": content.get("usage_constraints", []),
                    }
                ),
            }
        )
        for flow_name in _strings(content.get("applicable_flows")):
            if valid_flow and flow_name != valid_flow:
                continue
            add_edge(f"flow:{flow_name}", node_id, "uses_template", template_type=content.get("template_type", ""))

    for binding in bindings:
        content = binding.get("content", {}) if isinstance(binding.get("content", {}), dict) else {}
        knowledge_id = str(content.get("knowledge_id") or "")
        flow_name = str(content.get("flow") or "")
        knowledge_node_id = f"knowledge:{knowledge_id}"
        flow_node_id = f"flow:{flow_name}"
        add_edge(
            knowledge_node_id,
            flow_node_id,
            "bound_to_flow",
            binding_id=binding.get("id", ""),
            usage_type=content.get("usage_type", ""),
            input_role=content.get("input_role", ""),
            output_form=content.get("output_form", ""),
            priority=content.get("priority", 100),
        )
        rule_id = str(content.get("review_rule_id") or "")
        if rule_id and rule_id in rule_by_id:
            add_edge(knowledge_node_id, f"rule:{rule_id}", "validated_by_rule", binding_id=binding.get("id", ""))
        template_id = str(content.get("template_id") or "")
        if template_id and template_id in template_by_id:
            add_edge(knowledge_node_id, f"template:{template_id}", "instantiates_template", binding_id=binding.get("id", ""))

    for relation in list_knowledge_relations(storage, project_id=project_id if project_id != "local-system" else None, limit=2000):
        content = relation.get("content", {}) if isinstance(relation.get("content", {}), dict) else {}
        source_id = f"knowledge:{content.get('source_knowledge_id', '')}"
        target_id = f"knowledge:{content.get('target_knowledge_id', '')}"
        relation_type = str(content.get("relation_type") or "supports")
        add_edge(
            source_id,
            target_id,
            relation_type,
            relation_asset_id=relation.get("id", ""),
            strength=content.get("strength", 0.7),
            confidence=content.get("confidence", 0.7),
            evidence_refs=content.get("evidence_refs", []),
            explanation=content.get("explanation", ""),
        )

    observed_pairs: set[tuple[str, str]] = set()
    for event in usage_events:
        content = event.get("content", {}) if isinstance(event.get("content", {}), dict) else {}
        knowledge_id = str(content.get("knowledge_id") or "")
        flow_name = str(content.get("flow") or "")
        if knowledge_id in knowledge_ids and (not valid_flow or flow_name == valid_flow):
            observed_pairs.add((knowledge_id, flow_name))
    for score in quality_scores:
        content = score.get("content", {}) if isinstance(score.get("content", {}), dict) else {}
        knowledge_id = str(content.get("knowledge_id") or "")
        flow_name = str(content.get("flow") or "")
        if knowledge_id in knowledge_ids and (not valid_flow or flow_name == valid_flow):
            observed_pairs.add((knowledge_id, flow_name))
    for knowledge_id, flow_name in observed_pairs:
        metrics = _knowledge_learning_metrics(knowledge_id, usage_events, quality_scores, flow_name)
        add_edge(
            f"knowledge:{knowledge_id}",
            f"flow:{flow_name}",
            "effect_observed",
            usage_count=metrics["usage_count"],
            observed_effect_count=metrics["observed_effect_count"],
            avg_effect_score=metrics["avg_effect_score"],
            feedback_delta=metrics["feedback_delta"],
            negative_signal_count=metrics["negative_signal_count"],
        )

    node_list = sorted(nodes.values(), key=lambda item: (str(item.get("node_type", "")), str(item.get("label", "")), str(item.get("id", ""))))
    edge_list = sorted(edges.values(), key=lambda item: (str(item.get("relation", "")), str(item.get("source", "")), str(item.get("target", ""))))
    graph_id = _stable_asset_id("knowledge_graph", project_id, valid_flow or "all", str(len(node_list)), str(len(edge_list)))
    return {
        "graph_id": graph_id,
        "project_id": project_id,
        "flow": valid_flow,
        "version": "mkaos-knowledge-graph-v1",
        "nodes": node_list,
        "edges": edge_list,
        "summary": _knowledge_graph_summary(node_list, edge_list),
        "source_isolation": {
            "raw_source_text_included": False,
            "source_chunk_ids_only": True,
            "clean_source_text_included": False,
            "graph_contains_abstract_knowledge_only": True,
        },
        "created_at": utc_now(),
    }


def _persist_knowledge_graph_snapshot(storage: LocalStorage, content: dict[str, Any], envelope: dict[str, Any]) -> Path:
    graph_id = str(content.get("graph_id") or make_id("knowledge_graph", utc_now()))
    asset = KnowledgeGraphSnapshot(
        id=graph_id,
        title=f"MKAOS knowledge graph {content.get('project_id')} {content.get('flow') or 'all'}",
        source="mkaos-knowledge-graph",
        tags=["mkaos", "knowledge-graph", "multidisciplinary", str(content.get("flow") or "all")],
        content=content,
        metadata={
            "project_id": content.get("project_id", ""),
            "mkaos": True,
            "use_in_generation_rag": False,
            "source_isolation": "no_raw_source_text",
            "run_metadata": run_metadata("mkaos.build_knowledge_graph", KnowledgeGraphSnapshot(title="knowledge graph", content={"nodes": [], "edges": []})),
            **envelope_asset_metadata(envelope),
        },
        references=_dedupe([str(node.get("asset_id") or "") for node in content.get("nodes", []) if str(node.get("asset_id") or "").strip()]),
    )
    _ensure_valid(asset.to_dict())
    return storage.write_asset("knowledge", asset)


def _persist_knowledge_learning_snapshot(storage: LocalStorage, content: dict[str, Any], envelope: dict[str, Any]) -> Path:
    learning_id = str(content.get("learning_id") or make_id("knowledge_learning", utc_now()))
    asset = KnowledgeLearningSnapshot(
        id=learning_id,
        title=f"MKAOS learning snapshot {content.get('project_id')} {content.get('flow') or 'all'}",
        source="mkaos-knowledge-effect-learning",
        tags=["mkaos", "knowledge-learning", "feedback-learning", str(content.get("flow") or "all")],
        content=content,
        metadata={
            "project_id": content.get("project_id", ""),
            "mkaos": True,
            "use_in_generation_rag": False,
            "source_isolation": "no_raw_source_text",
            "run_metadata": run_metadata("mkaos.learn_from_knowledge_effects", KnowledgeLearningSnapshot(title="knowledge learning", content={"learning_items": []})),
            **envelope_asset_metadata(envelope),
        },
        references=_dedupe([str(item.get("knowledge_id") or "") for item in content.get("learning_items", []) if str(item.get("knowledge_id") or "").strip()]),
    )
    _ensure_valid(asset.to_dict())
    return storage.write_asset("knowledge", asset)


def _knowledge_learning_content(
    storage: LocalStorage,
    *,
    project_id: str,
    flow: str = "",
    discipline: str = "",
    include_deprecated: bool = False,
    learning_rate: float = 0.25,
    limit: int = 500,
) -> dict[str, Any]:
    project_filter = project_id if project_id != "local-system" else None
    valid_flow = flow if flow in MKAOS_FLOWS else ""
    knowledge_rows = list_knowledge_cards(storage, project_id=project_filter, include_deprecated=include_deprecated, limit=limit)
    if discipline:
        needle = discipline.strip().lower()
        knowledge_rows = [row for row in knowledge_rows if needle in str(row.get("content", {}).get("discipline", "")).lower()]
    knowledge_ids = {str(row.get("id") or "") for row in knowledge_rows}
    usage_events = [
        row
        for row in list_usage_events(storage, project_id=project_filter, flow=valid_flow or None, limit=3000)
        if str(row.get("content", {}).get("knowledge_id") or "") in knowledge_ids
    ]
    quality_scores = [
        row
        for row in _list_quality_scores(storage, project_id=project_filter, flow=valid_flow or None, limit=3000)
        if str(row.get("content", {}).get("knowledge_id") or "") in knowledge_ids
    ]
    bindings = [
        row
        for row in list_usage_bindings(storage, flow=valid_flow or None, enabled=True, limit=2000)
        if str(row.get("content", {}).get("knowledge_id") or "") in knowledge_ids
        and _project_scope_matches(str(row.get("metadata", {}).get("project_id") or ""), project_id)
    ]
    learning_items: list[dict[str, Any]] = []
    for row in knowledge_rows:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        metadata = row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}
        knowledge_id = str(row.get("id") or "")
        candidate_flows = {valid_flow} if valid_flow else set()
        candidate_flows.update(str(binding.get("content", {}).get("flow") or "") for binding in bindings if str(binding.get("content", {}).get("knowledge_id") or "") == knowledge_id)
        candidate_flows.update(str(event.get("content", {}).get("flow") or "") for event in usage_events if str(event.get("content", {}).get("knowledge_id") or "") == knowledge_id)
        candidate_flows.update(str(score.get("content", {}).get("flow") or "") for score in quality_scores if str(score.get("content", {}).get("knowledge_id") or "") == knowledge_id)
        for item_flow in sorted(flow for flow in candidate_flows if flow) or [valid_flow or "review"]:
            metrics = _knowledge_learning_metrics(knowledge_id, usage_events, quality_scores, item_flow)
            current_weight = _float(content.get("weight", metadata.get("weight", 1.0)), 1.0)
            current_quality = _float(content.get("quality_score", metadata.get("quality_score", 0.7)), 0.7)
            risk_level = _normalize_risk_level(str(content.get("risk_level") or metadata.get("risk_level") or "low"))
            recommended_delta = _recommended_learning_delta(metrics, risk_level=risk_level, learning_rate=learning_rate)
            action = _recommended_learning_action(metrics, recommended_delta, risk_level=risk_level, status=str(content.get("status") or metadata.get("asset_status") or "active"))
            learning_items.append(
                {
                    "knowledge_id": knowledge_id,
                    "concept_name": str(content.get("concept_name") or row.get("title") or knowledge_id),
                    "flow": item_flow,
                    "discipline": content.get("discipline", ""),
                    "knowledge_type": content.get("knowledge_type", ""),
                    "status": content.get("status", metadata.get("asset_status", "")),
                    "risk_level": risk_level,
                    "quality_score": current_quality,
                    "current_weight": current_weight,
                    "learned_weight": max(0.0, round(current_weight + recommended_delta, 4)),
                    "recommended_weight_delta": recommended_delta,
                    "recommended_action": action,
                    "confidence": _learning_confidence(metrics),
                    "usage_count": metrics["usage_count"],
                    "observed_effect_count": metrics["observed_effect_count"],
                    "avg_effect_score": metrics["avg_effect_score"],
                    "feedback_delta": metrics["feedback_delta"],
                    "negative_signal_count": metrics["negative_signal_count"],
                    "positive_signal_count": metrics["positive_signal_count"],
                    "evidence_refs": _dedupe([knowledge_id, *[str(event.get("id") or "") for event in metrics["events"][:5]], *[str(score.get("id") or "") for score in metrics["quality_scores"][:5]]]),
                }
            )
    recommendations = [
        {
            "knowledge_id": item["knowledge_id"],
            "concept_name": item["concept_name"],
            "flow": item["flow"],
            "action": item["recommended_action"],
            "weight_delta": item["recommended_weight_delta"],
            "reason": _learning_recommendation_reason(item),
        }
        for item in learning_items
        if item["recommended_action"] not in {"observe", "keep"}
    ]
    return {
        "learning_id": _stable_asset_id("knowledge_learning", project_id, valid_flow or "all", str(len(learning_items)), str(len(recommendations))),
        "project_id": project_id,
        "flow": valid_flow,
        "version": "mkaos-effect-learning-v1",
        "learning_items": learning_items,
        "recommendations": recommendations,
        "applied_updates": [],
        "source_metrics": {
            "knowledge_count": len(knowledge_rows),
            "usage_event_count": len(usage_events),
            "quality_score_count": len(quality_scores),
            "binding_count": len(bindings),
            "recommendation_count": len(recommendations),
        },
        "source_isolation": {"raw_source_text_included": False, "source_chunk_ids_only": True, "event_payloads_aggregated_only": True},
        "created_at": utc_now(),
    }


def _knowledge_learning_metrics(
    knowledge_id: str,
    usage_events: list[dict[str, Any]],
    quality_scores: list[dict[str, Any]],
    flow: str,
) -> dict[str, Any]:
    events = [
        row
        for row in usage_events
        if str(row.get("content", {}).get("knowledge_id") or "") == knowledge_id
        and (not flow or str(row.get("content", {}).get("flow") or "") == flow)
    ]
    scores = [
        row
        for row in quality_scores
        if str(row.get("content", {}).get("knowledge_id") or "") == knowledge_id
        and (not flow or str(row.get("content", {}).get("flow") or "") == flow)
    ]
    observed_effect_scores: list[float] = []
    negative_signal_count = 0
    positive_signal_count = 0
    for event in events:
        content = event.get("content", {}) if isinstance(event.get("content", {}), dict) else {}
        review_result = content.get("review_result") if isinstance(content.get("review_result"), dict) else {}
        reader_feedback = content.get("reader_feedback") if isinstance(content.get("reader_feedback"), dict) else {}
        effect = _float(content.get("effect_score"), 0.0)
        if effect != 0.0 or review_result or reader_feedback:
            observed_effect_scores.append(max(0.0, min(1.0, effect)))
        if effect >= 0.7 or review_result.get("passed") or reader_feedback.get("sentiment") in {"positive", "delighted"}:
            positive_signal_count += 1
        if effect < 0.2 and (effect != 0.0 or review_result or reader_feedback):
            negative_signal_count += 1
        if review_result.get("anti_encyclopedia_hit") or review_result.get("canon_conflict_hit"):
            negative_signal_count += 1
        rating = _float(reader_feedback.get("rating"), -1.0)
        if 0 <= rating < 3:
            negative_signal_count += 1
        elif rating >= 4:
            positive_signal_count += 1
    feedback_delta = round(sum(_float(row.get("content", {}).get("delta"), 0.0) for row in scores), 4)
    positive_signal_count += len([row for row in scores if _float(row.get("content", {}).get("delta"), 0.0) > 0])
    negative_signal_count += len([row for row in scores if _float(row.get("content", {}).get("delta"), 0.0) < 0])
    avg_effect = None if not observed_effect_scores else round(sum(observed_effect_scores) / len(observed_effect_scores), 4)
    return {
        "events": events,
        "quality_scores": scores,
        "usage_count": len(events),
        "quality_score_count": len(scores),
        "observed_effect_count": len(observed_effect_scores),
        "avg_effect_score": avg_effect,
        "feedback_delta": feedback_delta,
        "negative_signal_count": negative_signal_count,
        "positive_signal_count": positive_signal_count,
    }


def _recommended_learning_delta(metrics: dict[str, Any], *, risk_level: str, learning_rate: float) -> float:
    has_signal = metrics["observed_effect_count"] > 0 or metrics["quality_score_count"] > 0
    if not has_signal:
        return 0.0
    effect_basis = _float(metrics.get("avg_effect_score"), 0.5)
    delta = (effect_basis - 0.5) * learning_rate
    delta += _float(metrics.get("feedback_delta"), 0.0) * min(1.0, learning_rate * 2)
    delta += (int(metrics.get("positive_signal_count", 0)) - int(metrics.get("negative_signal_count", 0))) * 0.02
    if risk_level in {"high", "critical"}:
        delta -= 0.05 if risk_level == "high" else 0.15
    return round(max(-0.4, min(0.4, delta)), 4)


def _recommended_learning_action(metrics: dict[str, Any], delta: float, *, risk_level: str, status: str) -> str:
    if status == "deprecated":
        return "do_not_select"
    if risk_level == "critical":
        return "quarantine"
    if int(metrics.get("negative_signal_count", 0)) >= 2:
        return "review"
    if delta >= 0.03:
        return "boost"
    if delta <= -0.03:
        return "reduce"
    if metrics["usage_count"] == 0 and metrics["quality_score_count"] == 0:
        return "observe"
    return "keep"


def _learning_confidence(metrics: dict[str, Any]) -> str:
    signal_count = int(metrics.get("observed_effect_count", 0)) + int(metrics.get("quality_score_count", 0))
    if signal_count >= 5:
        return "high"
    if signal_count >= 2:
        return "medium"
    if signal_count == 1:
        return "low"
    return "none"


def _learning_recommendation_reason(item: dict[str, Any]) -> str:
    if item["recommended_action"] == "quarantine":
        return "critical risk knowledge should be excluded until reviewed"
    if item["recommended_action"] == "review":
        return "negative effect or feedback signals exceeded review threshold"
    if item["recommended_action"] == "boost":
        return "observed effect or feedback delta supports stronger selection"
    if item["recommended_action"] == "reduce":
        return "observed effect or feedback delta supports weaker selection"
    if item["recommended_action"] == "do_not_select":
        return "knowledge is deprecated"
    return "no action"


def _list_quality_scores(storage: LocalStorage, *, project_id: str | None = None, flow: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
    rows = _list_assets(storage, "knowledge", "knowledge_quality_score", project_id=project_id, limit=limit)
    if flow:
        rows = [row for row in rows if str(row.get("content", {}).get("flow", "")) == flow]
    return rows


def _response_data(response: dict[str, Any]) -> dict[str, Any]:
    if isinstance(response, dict) and isinstance(response.get("data"), dict) and "success" in response:
        return response["data"]
    return response if isinstance(response, dict) else {}


def _evolve_review_rules_from_learning(
    storage: LocalStorage,
    project_id: str,
    flow: str,
    learning: dict[str, Any],
    attributions: list[dict[str, Any]],
    payload: dict[str, Any],
) -> dict[str, Any]:
    signals: list[dict[str, Any]] = []
    for item in learning.get("learning_items", []) if isinstance(learning.get("learning_items"), list) else []:
        if not isinstance(item, dict):
            continue
        action = str(item.get("recommended_action") or "")
        if action in {"review", "reduce", "quarantine", "do_not_select"}:
            signals.append(
                {
                    "signal_type": "knowledge_effect",
                    "knowledge_id": item.get("knowledge_id", ""),
                    "concept_name": item.get("concept_name", ""),
                    "flow": item.get("flow") or flow or "review",
                    "tags": [action],
                    "severity": "high" if action in {"quarantine", "do_not_select"} else "medium",
                    "reason": _learning_recommendation_reason(item),
                }
            )
    for row in attributions:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if content.get("sentiment") != "negative":
            continue
        tags = _strings(content.get("issue_tags"))
        if tags:
            signals.append(
                {
                    "signal_type": "reader_feedback",
                    "knowledge_id": (_strings(content.get("candidate_knowledge_ids")) or [""])[0],
                    "flow": flow or "review",
                    "tags": tags,
                    "severity": "medium",
                    "reason": "reader feedback exposed reusable review rule gap",
                }
            )
    candidates: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    seen: set[str] = set()
    for signal in signals[: int(payload.get("max_rule_candidates", 6) or 6)]:
        rule_payload = _rule_payload_from_evolution_signal(project_id, flow, signal)
        signature = _stable_asset_id("rule_evolution", project_id, rule_payload["rule_name"], ",".join(rule_payload["check_items"]))
        if signature in seen:
            continue
        seen.add(signature)
        if bool(payload.get("apply_rule_updates", False)) or _rule_auto_apply_allowed(signal, rule_payload, payload):
            created = create_rule_card(storage, {**rule_payload, "enabled": True, "os_envelope": payload.get("os_envelope") or payload.get("envelope"), "environment": payload.get("environment", ""), "source_policy": payload.get("source_policy", {})})
            applied.append({"asset_id": created["asset"]["id"], "rule_name": rule_payload["rule_name"], "path": created["path"], "auto_applied": not bool(payload.get("apply_rule_updates", False))})
        else:
            candidates.append(_persist_rule_card_candidate(storage, project_id, signal, rule_payload))
    mode = "apply" if payload.get("apply_rule_updates") else "guarded_auto" if applied and payload.get("auto_apply_safe_actions") else "candidate"
    return {"mode": mode, "signals": signals, "candidates": candidates, "applied": applied}


def _backflow_templates_from_learning(
    storage: LocalStorage,
    project_id: str,
    flow: str,
    learning: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    seen: set[str] = set()
    boost_items = [
        item
        for item in learning.get("learning_items", []) if isinstance(learning.get("learning_items"), list)
        if isinstance(item, dict) and str(item.get("recommended_action") or "") == "boost"
    ]
    for item in boost_items[: int(payload.get("max_template_candidates", 6) or 6)]:
        knowledge_id = str(item.get("knowledge_id") or "")
        signature = _stable_asset_id("template_backflow", project_id, knowledge_id, flow or str(item.get("flow") or "outline"))
        if signature in seen:
            continue
        seen.add(signature)
        if knowledge_id and (bool(payload.get("apply_template_updates", False)) or _template_auto_apply_allowed(item, payload)):
            created = knowledge_to_application_template(storage, knowledge_id, {"project_id": project_id, "flow": flow or str(item.get("flow") or "outline")})
            applied.append({"asset_id": created["asset"]["id"], "template_name": created["asset"]["content"].get("template_name", ""), "path": created["path"], "auto_applied": not bool(payload.get("apply_template_updates", False))})
        else:
            candidates.append(_persist_template_card_candidate(storage, project_id, item, flow))
    hot_templates = payload.get("hot_deconstruction_templates") if isinstance(payload.get("hot_deconstruction_templates"), list) else []
    for hot in hot_templates[: int(payload.get("max_hot_template_candidates", 4) or 4)]:
        if not isinstance(hot, dict):
            continue
        item = {
            "knowledge_id": str(hot.get("knowledge_id") or ""),
            "concept_name": str(hot.get("pattern_name") or hot.get("template_name") or "爆款拆解模板"),
            "flow": str(hot.get("flow") or flow or "chapter_outline"),
            "platform": str(hot.get("platform") or ""),
            "genre": str(hot.get("genre") or ""),
            "source": "hot_deconstruction_backflow",
            "template_structure": hot.get("template_structure") if isinstance(hot.get("template_structure"), dict) else {},
        }
        candidates.append(_persist_template_card_candidate(storage, project_id, item, item["flow"]))
    mode = "apply" if payload.get("apply_template_updates") else "guarded_auto" if applied and payload.get("auto_apply_safe_actions") else "candidate"
    return {"mode": mode, "candidates": candidates, "applied": applied}


def _low_effect_knowledge_elimination(storage: LocalStorage, project_id: str, flow: str, learning: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    recommendations: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    for item in learning.get("learning_items", []) if isinstance(learning.get("learning_items"), list) else []:
        if not isinstance(item, dict):
            continue
        action = str(item.get("recommended_action") or "")
        avg_effect = item.get("avg_effect_score")
        negative_count = int(item.get("negative_signal_count", 0) or 0)
        usage_count = int(item.get("usage_count", 0) or 0)
        status_action = ""
        if action == "quarantine":
            status_action = "quarantined"
        elif action == "do_not_select":
            status_action = "do_not_select"
        elif negative_count >= 3 or (usage_count >= 3 and avg_effect is not None and _float(avg_effect, 0.5) < 0.25):
            status_action = "quarantined"
        elif action in {"review", "reduce"}:
            status_action = "needs_review"
        if not status_action:
            continue
        recommendation = {
            "knowledge_id": item.get("knowledge_id", ""),
            "concept_name": item.get("concept_name", ""),
            "flow": item.get("flow") or flow,
            "recommended_status": status_action,
            "recommended_action": action,
            "reason": _learning_recommendation_reason(item),
            "usage_count": usage_count,
            "negative_signal_count": negative_count,
            "avg_effect_score": avg_effect,
        }
        recommendations.append(recommendation)
        if recommendation["knowledge_id"] and (bool(payload.get("apply_elimination", False)) or _elimination_auto_apply_allowed(recommendation, payload)):
            changed = change_knowledge_status(storage, str(recommendation["knowledge_id"]), {"status": status_action, "reason": "knowledge_evolution_low_effect", "actor": "mkaos_evolution", "trace_id": str(payload.get("trace_id") or "")})
            applied.append({"knowledge_id": recommendation["knowledge_id"], "status": changed["asset"]["content"].get("status", ""), "path": changed["path"], "auto_applied": not bool(payload.get("apply_elimination", False))})
    mode = "apply" if payload.get("apply_elimination") else "guarded_auto" if applied and payload.get("auto_apply_safe_actions") else "recommendation"
    return {"mode": mode, "recommendations": recommendations, "applied": applied}


def _create_evolution_approval_requests(
    storage: LocalStorage,
    project_id: str,
    flow: str,
    rule_evolution: dict[str, Any],
    template_backflow: dict[str, Any],
    elimination: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not (bool(payload.get("create_approval_requests", False)) or str(payload.get("evolution_mode") or "") == "human_approval"):
        return {"mode": "not_requested", "approval_count": 0, "approvals": []}
    approvals: list[dict[str, Any]] = []
    for candidate in rule_evolution.get("candidates", []) if isinstance(rule_evolution.get("candidates"), list) else []:
        action_payload = {"candidate_id": str(candidate.get("candidate_id") or ""), "rule_payload": candidate.get("rule_payload") if isinstance(candidate.get("rule_payload"), dict) else {}}
        approval = create_governance_approval(
            storage,
            {
                **payload,
                "project_id": project_id,
                "flow": flow,
                "approval_type": "activate_rule",
                "action_type": "activate_rule",
                "risk_level": "medium",
                "reason": f"Review rule candidate from MKAOS learning: {candidate.get('rule_name') or candidate.get('candidate_id')}",
                "action_payload": action_payload,
                "references": [str(candidate.get("candidate_id") or "")],
            },
        )
        approvals.append({"approval_id": approval["asset"]["id"], "action_type": "activate_rule", "status": "pending", "path": approval["path"]})
    for candidate in template_backflow.get("candidates", []) if isinstance(template_backflow.get("candidates"), list) else []:
        action_payload = {"candidate_id": str(candidate.get("candidate_id") or ""), "template_payload": candidate.get("template_payload") if isinstance(candidate.get("template_payload"), dict) else {}}
        approval = create_governance_approval(
            storage,
            {
                **payload,
                "project_id": project_id,
                "flow": flow,
                "approval_type": "activate_template",
                "action_type": "activate_template",
                "risk_level": "low",
                "reason": f"Template candidate from MKAOS learning: {candidate.get('template_name') or candidate.get('candidate_id')}",
                "action_payload": action_payload,
                "references": [str(candidate.get("candidate_id") or ""), str(candidate.get("source_knowledge_id") or "")],
            },
        )
        approvals.append({"approval_id": approval["asset"]["id"], "action_type": "activate_template", "status": "pending", "path": approval["path"]})
    for recommendation in elimination.get("recommendations", []) if isinstance(elimination.get("recommendations"), list) else []:
        approval = create_governance_approval(
            storage,
            {
                **payload,
                "project_id": project_id,
                "flow": flow,
                "approval_type": "status_change",
                "action_type": "quarantine_knowledge" if recommendation.get("recommended_status") == "quarantined" else "change_knowledge_status",
                "risk_level": "high" if recommendation.get("recommended_status") in {"quarantined", "do_not_select"} else "medium",
                "reason": str(recommendation.get("reason") or "low effect knowledge recommendation"),
                "action_payload": recommendation,
                "references": [str(recommendation.get("knowledge_id") or "")],
            },
        )
        approvals.append({"approval_id": approval["asset"]["id"], "action_type": approval["asset"]["content"].get("action_type", ""), "status": "pending", "path": approval["path"]})
    return {"mode": "human_approval", "approval_count": len(approvals), "approvals": approvals}


def _apply_governance_approval_action(storage: LocalStorage, approval_content: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    action_type = str(approval_content.get("action_type") or "")
    action_payload = approval_content.get("action_payload") if isinstance(approval_content.get("action_payload"), dict) else {}
    project_id = str(approval_content.get("project_id") or payload.get("project_id") or "local-system")
    if action_type == "approve_knowledge_candidate":
        candidate_id = str(action_payload.get("candidate_id") or "")
        if not candidate_id:
            return {"applied": False, "reason": "missing_candidate_id"}
        approved = approve_knowledge_candidate(storage, candidate_id, {"project_id": project_id, "actor": payload.get("actor") or "operator"})
        return {"applied": True, "asset_type": "knowledge_card", "asset_id": approved["knowledge"]["asset"]["id"], "candidate_id": candidate_id, "path": approved["knowledge"]["path"]}
    if action_type == "activate_rule":
        rule_payload = action_payload.get("rule_payload") if isinstance(action_payload.get("rule_payload"), dict) else {}
        if not rule_payload and action_payload.get("candidate_id"):
            _, candidate = _find_asset(storage, str(action_payload.get("candidate_id")), asset_type="rule_card_candidate", categories=["quality_standards"])
            rule_payload = candidate.get("content", {}).get("rule_payload", {}) if isinstance(candidate.get("content"), dict) else {}
        if not rule_payload:
            return {"applied": False, "reason": "missing_rule_payload"}
        created = create_rule_card(storage, {**rule_payload, "project_id": project_id, "enabled": True, "actor": payload.get("actor") or "operator"})
        return {"applied": True, "asset_type": "rule_card", "asset_id": created["asset"]["id"], "path": created["path"]}
    if action_type == "activate_template":
        template_payload = action_payload.get("template_payload") if isinstance(action_payload.get("template_payload"), dict) else {}
        source_knowledge_id = str(template_payload.get("source_knowledge_id") or action_payload.get("source_knowledge_id") or "")
        if not template_payload and action_payload.get("candidate_id"):
            _, candidate = _find_asset(storage, str(action_payload.get("candidate_id")), asset_type="template_card_candidate", categories=["templates"])
            template_payload = candidate.get("content", {}) if isinstance(candidate.get("content"), dict) else {}
            source_knowledge_id = str(template_payload.get("source_knowledge_id") or "")
        if source_knowledge_id:
            created = knowledge_to_application_template(storage, source_knowledge_id, {"project_id": project_id, "flow": str(template_payload.get("flow") or approval_content.get("flow") or "outline")})
            return {"applied": True, "asset_type": "template_card", "asset_id": created["asset"]["id"], "path": created["path"]}
        created = create_template_card(
            storage,
            {
                "project_id": project_id,
                "template_name": str(template_payload.get("template_name") or "MKAOS approved application template"),
                "template_type": str(template_payload.get("template_type") or "outline_template"),
                "structure": template_payload.get("output_structure") or ["pressure", "choice", "cost", "hook"],
                "usage_constraints": template_payload.get("forbidden_usage") or ["no raw source expression", "no encyclopedia paragraph"],
                "applicable_flows": [str(template_payload.get("flow") or approval_content.get("flow") or "outline")],
            },
        )
        return {"applied": True, "asset_type": "template_card", "asset_id": created["asset"]["id"], "path": created["path"]}
    if action_type in {"quarantine_knowledge", "change_knowledge_status"}:
        knowledge_id = str(action_payload.get("knowledge_id") or "")
        if not knowledge_id:
            return {"applied": False, "reason": "missing_knowledge_id"}
        changed = change_knowledge_status(
            storage,
            knowledge_id,
            {
                "status": str(action_payload.get("recommended_status") or "needs_review"),
                "reason": str(action_payload.get("reason") or "approved_governance_action"),
                "actor": payload.get("actor") or "operator",
                "trace_id": payload.get("trace_id") or approval_content.get("trace_id") or "",
            },
        )
        return {"applied": True, "asset_type": "knowledge_card", "asset_id": changed["asset"]["id"], "status": changed["asset"]["content"].get("status", ""), "path": changed["path"]}
    return {"applied": False, "reason": f"unsupported_action:{action_type}"}


def _rule_payload_from_evolution_signal(project_id: str, flow: str, signal: dict[str, Any]) -> dict[str, Any]:
    tags = set(_strings(signal.get("tags")))
    rule_type = "knowledge_effectiveness"
    check_items = ["知识必须转化为人物行动、冲突、选择代价或审稿检查"]
    fix_suggestion = "把知识从说明改写为行动、冲突、物件、线索或章节钩子。"
    if {"worldbuilding_overload", "template_overuse", "ai_style"} & tags:
        rule_type = "anti_encyclopedia"
        check_items = ["禁止资料卡式说明", "知识必须改变角色行动或场景状态"]
    elif "pacing" in tags:
        rule_type = "chapter_rhythm"
        check_items = ["章节中段必须有压力变化", "结尾必须形成下一章期待"]
        fix_suggestion = "减少解释密度，把知识压缩为阻碍、反转或选择代价。"
    elif "payoff_density" in tags or "reversal" in tags:
        rule_type = "payoff_density"
        check_items = ["知识必须制造可感知收益、落差或反转"]
    elif "mystery_clue" in tags:
        rule_type = "causal_chain"
        check_items = ["线索必须公平可复盘", "误导和真相都要有证据位置"]
    elif "source_leakage" in tags:
        rule_type = "source_isolation"
        check_items = ["禁止来源原文表达进入正文", "仅允许 evidence id/hash 和抽象机制"]
    concept = str(signal.get("concept_name") or signal.get("knowledge_id") or "MKAOS knowledge")
    return {
        "project_id": project_id,
        "rule_name": f"{concept} 进化审稿规则",
        "rule_type": rule_type,
        "trigger_condition": f"{concept} 进入 {flow or signal.get('flow') or 'review'} flow 或反馈命中 {','.join(sorted(tags))}",
        "check_items": check_items,
        "severity": str(signal.get("severity") or "medium"),
        "blocking": "source_leakage" in tags,
        "fix_suggestion": fix_suggestion,
        "applicable_flows": [flow or str(signal.get("flow") or "review")],
    }


def _rule_auto_apply_allowed(signal: dict[str, Any], rule_payload: dict[str, Any], payload: dict[str, Any]) -> bool:
    if not bool(payload.get("auto_apply_safe_actions", False)):
        return False
    severity = str(rule_payload.get("severity") or signal.get("severity") or "medium")
    rule_type = str(rule_payload.get("rule_type") or "")
    if severity == "critical":
        return False
    return rule_type in {"anti_encyclopedia", "chapter_rhythm", "payoff_density", "causal_chain", "source_isolation", "knowledge_effectiveness"}


def _template_auto_apply_allowed(item: dict[str, Any], payload: dict[str, Any]) -> bool:
    if not bool(payload.get("auto_apply_safe_actions", False)):
        return False
    confidence = str(item.get("confidence") or "")
    usage_count = int(item.get("usage_count", 0) or 0)
    avg_effect = item.get("avg_effect_score")
    threshold = _float(payload.get("auto_template_activation_threshold"), 0.7)
    if confidence == "none":
        return False
    if avg_effect is not None and _float(avg_effect, 0.0) >= threshold:
        return True
    return usage_count >= 2 and str(item.get("recommended_action") or "") == "boost"


def _elimination_auto_apply_allowed(recommendation: dict[str, Any], payload: dict[str, Any]) -> bool:
    if not bool(payload.get("auto_apply_safe_actions", False)):
        return False
    threshold = int(payload.get("auto_elimination_threshold", 3) or 3)
    recommended_status = str(recommendation.get("recommended_status") or "")
    negative_count = int(recommendation.get("negative_signal_count", 0) or 0)
    avg_effect = recommendation.get("avg_effect_score")
    if recommended_status not in {"quarantined", "do_not_select"}:
        return False
    if negative_count >= threshold:
        return True
    return avg_effect is not None and _float(avg_effect, 0.5) <= 0.15 and int(recommendation.get("usage_count", 0) or 0) >= threshold


def _persist_rule_card_candidate(storage: LocalStorage, project_id: str, signal: dict[str, Any], rule_payload: dict[str, Any]) -> dict[str, Any]:
    candidate_id = _stable_asset_id("rule_card_candidate", project_id, rule_payload["rule_name"], ",".join(rule_payload["check_items"]))
    content = {
        "candidate_id": candidate_id,
        "candidate_type": "rule_card_candidate",
        "source_signal": signal,
        "rule_payload": rule_payload,
        "status": "needs_review",
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
    }
    asset = _base_asset(
        "rule_card_candidate",
        asset_id=candidate_id,
        title=rule_payload["rule_name"],
        source="mkaos-knowledge-evolution",
        tags=["mkaos", "rule-card-candidate", rule_payload["rule_type"], "needs-review"],
        content=content,
        metadata={"project_id": project_id, "mkaos": True, "asset_status": "needs_review", "use_in_generation_rag": False},
        references=_dedupe([str(signal.get("knowledge_id") or "")]),
    )
    path = storage.write_asset("quality_standards", asset)
    return {
        "candidate_id": candidate_id,
        "path": _display_path(storage.root, path),
        "rule_name": rule_payload["rule_name"],
        "rule_type": rule_payload["rule_type"],
        "rule_payload": rule_payload,
        "status": "needs_review",
    }


def _persist_template_card_candidate(storage: LocalStorage, project_id: str, item: dict[str, Any], flow: str) -> dict[str, Any]:
    name = str(item.get("concept_name") or item.get("template_name") or "MKAOS application template")
    candidate_id = _stable_asset_id("template_card_candidate", project_id, name, flow)
    content = {
        "candidate_id": candidate_id,
        "candidate_type": "template_card_candidate",
        "template_name": f"{name} 应用模板",
        "template_type": f"{flow or 'outline'}_template",
        "source_knowledge_id": str(item.get("knowledge_id") or ""),
        "flow": flow or str(item.get("flow") or "outline"),
        "platform": str(item.get("platform") or ""),
        "genre": str(item.get("genre") or ""),
        "input_fields": ["task_goal", "current_story_context", "character_pressure", "platform_profile"],
        "output_structure": item.get("template_structure") if isinstance(item.get("template_structure"), dict) else {"beats": ["pressure", "choice", "cost", "payoff", "hook"]},
        "application_steps": ["select abstract mechanism", "bind it to character choice", "show visible cost", "add review check"],
        "forbidden_usage": ["raw source expression", "encyclopedia paragraph", "direct platform-rule lecture"],
        "success_criteria": ["knowledge changes action", "scene has visible conflict", "no source leakage"],
        "status": "needs_review",
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
    }
    asset = _base_asset(
        "template_card_candidate",
        asset_id=candidate_id,
        title=content["template_name"],
        source=str(item.get("source") or "mkaos-knowledge-evolution"),
        tags=["mkaos", "template-card-candidate", content["template_type"], "needs-review"],
        content=content,
        metadata={"project_id": project_id, "mkaos": True, "asset_status": "needs_review", "use_in_generation_rag": False},
        references=_dedupe([content["source_knowledge_id"]]),
    )
    path = storage.write_asset("templates", asset)
    return {
        "candidate_id": candidate_id,
        "path": _display_path(storage.root, path),
        "template_name": content["template_name"],
        "template_type": content["template_type"],
        "source_knowledge_id": content["source_knowledge_id"],
        "template_payload": content,
        "status": "needs_review",
    }


def _top_feedback_tags(attributions: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in attributions:
        for tag in _strings(row.get("content", {}).get("issue_tags") if isinstance(row.get("content"), dict) else []):
            counts[tag] = counts.get(tag, 0) + 1
    return [{"tag": tag, "count": count} for tag, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def _knowledge_graph_summary(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    node_counts: dict[str, int] = {}
    relation_counts: dict[str, int] = {}
    discipline_counts: dict[str, int] = {}
    for node in nodes:
        node_type = str(node.get("node_type") or "unknown")
        node_counts[node_type] = node_counts.get(node_type, 0) + 1
        if node_type == "knowledge_card":
            discipline = str(node.get("attributes", {}).get("discipline") or "general")
            discipline_counts[discipline] = discipline_counts.get(discipline, 0) + 1
    for edge in edges:
        relation = str(edge.get("relation") or "unknown")
        relation_counts[relation] = relation_counts.get(relation, 0) + 1
    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "coverage": node_counts,
        "discipline_counts": discipline_counts,
        "edge_relation_counts": relation_counts,
        "reasoning_affordances": ["discipline traversal", "flow binding", "rule/template reuse", "effect learning", "evidence lineage"],
    }


def _knowledge_graph_explorer_content(graph: dict[str, Any], *, max_nodes: int, max_frames: int) -> dict[str, Any]:
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    sampled_nodes = nodes[: max(1, max_nodes)]
    sampled_ids = {str(node.get("id") or "") for node in sampled_nodes}
    sampled_edges = [edge for edge in edges if str(edge.get("source") or "") in sampled_ids and str(edge.get("target") or "") in sampled_ids]
    node_by_id = {str(node.get("id") or ""): node for node in sampled_nodes}
    clusters: dict[str, dict[str, Any]] = {}
    for node in sampled_nodes:
        node_type = str(node.get("node_type") or "unknown")
        attrs = node.get("attributes", {}) if isinstance(node.get("attributes"), dict) else {}
        if node_type == "knowledge_card":
            cluster_id = f"discipline:{attrs.get('discipline') or 'general'}"
        else:
            cluster_id = node_type
        cluster = clusters.setdefault(cluster_id, {"cluster_id": cluster_id, "label": cluster_id.replace("discipline:", ""), "node_type": node_type, "node_ids": []})
        cluster["node_ids"].append(str(node.get("id") or ""))
    sorted_clusters = sorted(clusters.values(), key=lambda item: (str(item.get("node_type") or ""), str(item.get("label") or "")))
    layout = _deterministic_cluster_layout(sampled_nodes, sorted_clusters)
    frames = _graph_path_animation_frames(sampled_edges[: max(0, max_frames)], node_by_id)
    explorer_id = _stable_asset_id(
        "knowledge_graph_explorer",
        str(graph.get("graph_id") or ""),
        str(len(sampled_nodes)),
        str(len(sampled_edges)),
        str(len(sorted_clusters)),
    )
    return {
        "explorer_report_id": explorer_id,
        "graph_id": graph.get("graph_id", ""),
        "project_id": graph.get("project_id", ""),
        "flow": graph.get("flow", ""),
        "version": "mkaos-graph-explorer-v2",
        "summary": graph.get("summary", {}),
        "nodes": sampled_nodes,
        "edges": sampled_edges,
        "clusters": sorted_clusters,
        "layout": layout,
        "path_animation_frames": frames,
        "large_graph_policy": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "sampled_nodes": len(sampled_nodes),
            "sampled_edges": len(sampled_edges),
            "max_nodes": max_nodes,
            "max_frames": max_frames,
            "layout_mode": "deterministic_clustered_radial",
        },
        "source_isolation": {"raw_text_included": False, "clean_text_included": False, "evidence_nodes_ids_only": True},
        "created_at": utc_now(),
    }


def _deterministic_cluster_layout(nodes: list[dict[str, Any]], clusters: list[dict[str, Any]]) -> dict[str, Any]:
    cluster_count = max(1, len(clusters))
    cluster_centers: dict[str, dict[str, float]] = {}
    positions: dict[str, dict[str, float | str]] = {}
    for cluster_index, cluster in enumerate(clusters):
        angle = (3.141592653589793 * 2 * cluster_index) / cluster_count
        center = {"x": round(500 + 320 * math.cos(angle), 2), "y": round(360 + 220 * math.sin(angle), 2)}
        cluster_id = str(cluster.get("cluster_id") or "")
        cluster_centers[cluster_id] = center
        node_ids = [str(item) for item in cluster.get("node_ids", []) if str(item)]
        node_count = max(1, len(node_ids))
        for node_index, node_id in enumerate(node_ids):
            inner_angle = (3.141592653589793 * 2 * node_index) / node_count
            positions[node_id] = {
                "x": round(center["x"] + 52 * math.cos(inner_angle), 2),
                "y": round(center["y"] + 38 * math.sin(inner_angle), 2),
                "cluster_id": cluster_id,
            }
    return {"mode": "deterministic_clustered_radial", "cluster_centers": cluster_centers, "positions": positions}


def _graph_path_animation_frames(edges: list[dict[str, Any]], node_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for index, edge in enumerate(edges):
        source = node_by_id.get(str(edge.get("source") or ""), {})
        target = node_by_id.get(str(edge.get("target") or ""), {})
        frames.append(
            {
                "frame": index + 1,
                "edge_id": str(edge.get("id") or f"{edge.get('source')}-{edge.get('target')}-{edge.get('relation')}"),
                "relation": str(edge.get("relation") or ""),
                "source": str(edge.get("source") or ""),
                "target": str(edge.get("target") or ""),
                "source_label": str(source.get("label") or edge.get("source") or ""),
                "target_label": str(target.get("label") or edge.get("target") or ""),
                "explanation": f"{source.get('label') or edge.get('source')} --{edge.get('relation')}--> {target.get('label') or edge.get('target')}",
            }
        )
    return frames

def _source_chunk_graph_node(storage: LocalStorage, chunk_id: str) -> dict[str, Any] | None:
    try:
        _, chunk = _find_asset(storage, chunk_id, asset_type="source_chunk", categories=["raw"])
    except FileNotFoundError:
        return None
    content = chunk.get("content", {}) if isinstance(chunk.get("content", {}), dict) else {}
    metadata = chunk.get("metadata", {}) if isinstance(chunk.get("metadata", {}), dict) else {}
    return {
        "id": f"source_chunk:{chunk_id}",
        "node_type": "source_chunk",
        "asset_id": chunk_id,
        "label": f"source chunk {content.get('chunk_index', '')}".strip(),
        "attributes": _safe_graph_attrs(
            {
                "source_document_id": content.get("source_document_id", ""),
                "chunk_index": content.get("chunk_index", 0),
                "content_hash": content.get("content_hash", ""),
                "project_id": metadata.get("project_id", ""),
            }
        ),
    }


def _first_knowledge_flow(
    knowledge_id: str,
    bindings: list[dict[str, Any]],
    usage_events: list[dict[str, Any]],
    quality_scores: list[dict[str, Any]],
) -> str:
    for rows in [bindings, usage_events, quality_scores]:
        for row in rows:
            content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
            if str(content.get("knowledge_id") or "") == knowledge_id and str(content.get("flow") or ""):
                return str(content.get("flow") or "")
    return "review"


def _graph_node_matches_terms(node: dict[str, Any], terms: list[str]) -> bool:
    haystack = json.dumps(
        {
            "id": node.get("id", ""),
            "label": node.get("label", ""),
            "node_type": node.get("node_type", ""),
            "asset_id": node.get("asset_id", ""),
            "attributes": node.get("attributes", {}),
        },
        ensure_ascii=False,
    ).lower()
    return all(term in haystack for term in terms)


def _find_graph_paths(graph: dict[str, Any], source: str, target: str, *, max_depth: int) -> list[dict[str, Any]]:
    node_by_id = {str(node.get("id")): node for node in graph.get("nodes", [])}
    source_ids = _resolve_graph_node_ids(node_by_id, source)
    target_ids = _resolve_graph_node_ids(node_by_id, target)
    if not source_ids or not target_ids:
        return []
    adjacency: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for edge in graph.get("edges", []):
        source_id = str(edge.get("source") or "")
        target_id = str(edge.get("target") or "")
        adjacency.setdefault(source_id, []).append((target_id, edge))
        adjacency.setdefault(target_id, []).append((source_id, edge))
    paths: list[dict[str, Any]] = []
    queue: list[tuple[str, list[str], list[dict[str, Any]]]] = [(node_id, [node_id], []) for node_id in source_ids]
    while queue and len(paths) < 10:
        node_id, node_path, edge_path = queue.pop(0)
        if node_id in target_ids and edge_path:
            paths.append(
                {
                    "nodes": [node_by_id[item] for item in node_path if item in node_by_id],
                    "edges": edge_path,
                    "relation_path": [str(edge.get("relation") or "") for edge in edge_path],
                    "explanation": " -> ".join(str(node_by_id[item].get("label") or item) for item in node_path if item in node_by_id),
                }
            )
            continue
        if len(edge_path) >= max_depth:
            continue
        for next_id, edge in adjacency.get(node_id, []):
            if next_id in node_path:
                continue
            queue.append((next_id, [*node_path, next_id], [*edge_path, edge]))
    return paths


def _resolve_graph_node_ids(node_by_id: dict[str, dict[str, Any]], value: str) -> set[str]:
    needle = value.strip().lower()
    matches: set[str] = set()
    for node_id, node in node_by_id.items():
        aliases = {
            node_id.lower(),
            str(node.get("asset_id") or "").lower(),
            str(node.get("label") or "").lower(),
        }
        if needle in aliases or needle in str(node.get("label") or "").lower():
            matches.add(node_id)
    return matches


def _safe_graph_attrs(value: dict[str, Any]) -> dict[str, Any]:
    return _strip_source_text_fields(value) if isinstance(value, dict) else {}


def _strip_source_text_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _strip_source_text_fields(item)
            for key, item in value.items()
            if str(key) not in {"raw_text", "clean_text", "text", "content_text", "source_text"}
        }
    if isinstance(value, list):
        return [_strip_source_text_fields(item) for item in value]
    return value


def _pack_item_from_binding(
    storage: LocalStorage,
    binding: dict[str, Any],
    flow: str,
    *,
    genre: str,
    platform: str,
    project_id: str = "",
    selector_policy: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    content = binding.get("content", {})
    binding_project_id = str(binding.get("metadata", {}).get("project_id") or "")
    if not _project_scope_matches(binding_project_id, project_id):
        return None
    knowledge_id = str(content.get("knowledge_id") or "")
    if not knowledge_id:
        return None
    try:
        _, knowledge = _find_asset(storage, knowledge_id, asset_type="knowledge_card", categories=["knowledge"])
    except FileNotFoundError:
        return None
    if not _project_scope_matches(str(knowledge.get("metadata", {}).get("project_id") or ""), project_id):
        return None
    status = _normalize_knowledge_status(_knowledge_status(knowledge))
    if status in DO_NOT_SELECT_STATUSES or (status == "needs_review" and is_production_environment(str((selector_policy or {}).get("environment") or ""))):
        return None
    kcontent = knowledge.get("content", {}) if isinstance(knowledge.get("content", {}), dict) else {}
    if not _genre_matches(kcontent.get("applicable_genres", []), genre):
        return None
    if not _platform_matches(kcontent.get("applicable_platforms", []), platform):
        return None
    role = _pack_role_from_binding(content, flow)
    item = {
        "knowledge_id": knowledge_id,
        "binding_id": binding.get("id", ""),
        "item_role": role,
        "flow": flow,
        "concept_name": kcontent.get("concept_name") or knowledge.get("title") or knowledge_id,
        "concept_aliases": kcontent.get("concept_aliases", []),
        "discipline": kcontent.get("discipline", ""),
        "sub_discipline": kcontent.get("sub_discipline", ""),
        "knowledge_type": kcontent.get("knowledge_type", ""),
        "core_explanation": kcontent.get("core_explanation") or " ".join(kcontent.get("principles", [])[:2]),
        "source_chunk_ids": kcontent.get("source_chunk_ids", []),
        "confidence": kcontent.get("confidence", 0),
        "quality_score": kcontent.get("quality_score", 0),
        "weight": kcontent.get("weight", 1.0),
        "usage_type": content.get("usage_type", ""),
        "usage_granularity": content.get("usage_granularity", ""),
        "input_role": content.get("input_role", ""),
        "output_form": content.get("output_form", ""),
        "prompt_fragment": content.get("prompt_fragment", ""),
        "constraint_text": content.get("constraint_text", ""),
        "review_rule_id": content.get("review_rule_id", ""),
        "template_id": content.get("template_id", ""),
        "priority": content.get("priority", 100),
        "risk_level": content.get("risk_level", kcontent.get("risk_level", "low")),
        "status": status,
        "applicable_genres": kcontent.get("applicable_genres", []),
        "applicable_platforms": kcontent.get("applicable_platforms", []),
        "platform_weights": kcontent.get("platform_weights", {}) if isinstance(kcontent.get("platform_weights", {}), dict) else {},
        "genre_weights": kcontent.get("genre_weights", {}) if isinstance(kcontent.get("genre_weights", {}), dict) else {},
        "quality_dimensions": kcontent.get("quality_dimensions", {}) if isinstance(kcontent.get("quality_dimensions", {}), dict) else {},
    }
    item["selector_decision"] = _selector_decision(storage, item, knowledge, binding, flow=flow, selector_policy=selector_policy or {})
    item["selection_score"] = item["selector_decision"]["selection_score"]
    item["quality_adjusted_score"] = item["selector_decision"]["quality_adjusted_score"]
    item["estimated_tokens"] = item["selector_decision"]["estimated_tokens"]
    return item


def _selector_policy(payload: dict[str, Any], os_envelope: dict[str, Any], budget: dict[str, Any]) -> dict[str, Any]:
    envelope_source_policy = os_envelope.get("source_policy", {}) if isinstance(os_envelope, dict) else {}
    source_policy = payload.get("source_policy") if isinstance(payload.get("source_policy"), dict) else envelope_source_policy
    excluded_risks = set(_strings(payload.get("exclude_risk_levels")))
    excluded_risks.update(_strings(source_policy.get("exclude_risk_levels") if isinstance(source_policy, dict) else None))
    excluded_risks.update(_strings(source_policy.get("blocked_risk_levels") if isinstance(source_policy, dict) else None))
    if isinstance(source_policy, dict) and source_policy.get("exclude_high_risk"):
        excluded_risks.update(["high", "critical"])
    if isinstance(source_policy, dict) and source_policy.get("exclude_critical_risk"):
        excluded_risks.add("critical")
    return {
        "version": "selector-v2",
        "selector_policy_version": "selector-v2",
        "selector_mode": "v2" if payload.get("current_goal") or payload.get("goal") or payload.get("task_goal") else "fallback",
        "fallback_reason": "" if payload.get("current_goal") or payload.get("goal") or payload.get("task_goal") else "task_goal_missing",
        "scoring": ["flow_match_score", "task_goal_relevance_score", "discipline_relevance_score", "platform_match_score", "genre_match_score", "priority_score", "weight_score", "quality_score", "effect_score", "review_pass_score", "reader_feedback_score", "risk_penalty", "review_issue_penalty", "status_penalty", "deprecated_penalty", "disabled_binding_penalty", "source_policy_penalty"],
        "source_policy": source_policy if isinstance(source_policy, dict) else {},
        "exclude_risk_levels": sorted({_normalize_risk_level(item) for item in excluded_risks if str(item).strip()}),
        "max_items": int(budget.get("max_items", 0) or 0),
        "max_selector_tokens": int((payload.get("knowledge_budget") if isinstance(payload.get("knowledge_budget"), dict) else {}).get("max_selector_tokens", 0) or 0),
        "task_goal": str(payload.get("task_goal") or payload.get("current_goal") or payload.get("goal") or ""),
        "genre": str(payload.get("genre") or ""),
        "platform": str(payload.get("platform") or ""),
        "discipline": str(payload.get("discipline") or ""),
        "agent_operation": str(payload.get("agent_operation") or payload.get("operation") or ""),
        "environment": str(os_envelope.get("environment") or payload.get("environment") or ""),
    }


def _selector_decision(
    storage: LocalStorage,
    item: dict[str, Any],
    knowledge: dict[str, Any],
    binding: dict[str, Any],
    *,
    flow: str,
    selector_policy: dict[str, Any],
) -> dict[str, Any]:
    risk_level = _normalize_risk_level(str(item.get("risk_level") or "low"))
    excluded_risks = set(_strings(selector_policy.get("exclude_risk_levels")))
    estimated_tokens = _estimate_pack_item_tokens(item)
    if risk_level in excluded_risks:
        return {
            "selected": False,
            "reason": "risk_excluded_by_source_policy",
            "selection_score": 0.0,
            "quality_adjusted_score": 0.0,
            "estimated_tokens": estimated_tokens,
            "risk_level": risk_level,
        }
    base_quality = _float(item.get("quality_score"), 0.7)
    quality_dimensions = item.get("quality_dimensions") if isinstance(item.get("quality_dimensions"), dict) else {}
    if quality_dimensions:
        base_quality = _overall_quality_score(quality_dimensions)
    feedback_delta = _quality_feedback_delta(storage, str(item.get("knowledge_id") or ""), flow)
    quality_adjusted = min(1.0, max(0.0, base_quality + feedback_delta))
    platform = str(selector_policy.get("platform") or "")
    genre = str(selector_policy.get("genre") or "")
    platform_weights = item.get("platform_weights") if isinstance(item.get("platform_weights"), dict) else {}
    genre_weights = item.get("genre_weights") if isinstance(item.get("genre_weights"), dict) else {}
    weight_source = "global"
    weight = max(0.0, _float(item.get("weight"), 1.0))
    if platform and platform in platform_weights:
        weight = max(0.0, _float(platform_weights.get(platform), weight))
        weight_source = f"platform:{platform}"
    elif genre and genre in genre_weights:
        weight = max(0.0, _float(genre_weights.get(genre), weight))
        weight_source = f"genre:{genre}"
    priority = int(item.get("priority", 100) or 100)
    priority_bonus = max(0.0, (100 - min(priority, 100)) / 100)
    risk_penalty = {"low": 0.0, "medium": 0.05, "high": 0.2, "critical": 0.45}.get(risk_level, 0.0)
    status = _normalize_knowledge_status(str(item.get("status") or "verified"))
    status_penalty = {"needs_review": 0.25, "deprecated": 1.0, "quarantined": 1.0, "do_not_select": 1.0}.get(status, 0.0)
    source_policy_penalty = 0.25 if _float(quality_dimensions.get("copyright_risk_score"), 0.1) >= 0.7 else 0.0
    task_goal_score = _term_relevance_score(str(selector_policy.get("task_goal") or ""), [str(item.get("concept_name") or ""), str(item.get("core_explanation") or ""), *[str(alias) for alias in item.get("concept_aliases", []) if isinstance(item.get("concept_aliases", []), list)]])
    discipline_score = _term_relevance_score(str(selector_policy.get("discipline") or ""), [str(item.get("discipline") or ""), str(item.get("sub_discipline") or "")])
    platform_score = 0.08 if platform and platform in _strings(item.get("applicable_platforms")) else 0.0
    genre_score = 0.08 if genre and genre in _strings(item.get("applicable_genres")) else 0.0
    recency_bonus = _recency_bonus(knowledge)
    role_bonus = 0.2 if item.get("item_role") in {"required", "review_rule"} else 0.0
    score = max(0.0, (quality_adjusted * weight) + priority_bonus + recency_bonus + role_bonus + task_goal_score + discipline_score + platform_score + genre_score - risk_penalty - status_penalty - source_policy_penalty)
    return {
        "selected": True,
        "reason": "selected",
        "selection_score": round(score, 4),
        "quality_adjusted_score": round(quality_adjusted, 4),
        "feedback_delta": round(feedback_delta, 4),
        "estimated_tokens": estimated_tokens,
        "risk_level": risk_level,
        "priority": priority,
        "weight": round(weight, 4),
        "weight_source": weight_source,
        "recency_bonus": round(recency_bonus, 4),
        "score_breakdown": {
            "flow_match_score": 1.0,
            "task_goal_relevance_score": round(task_goal_score, 4),
            "discipline_relevance_score": round(discipline_score, 4),
            "platform_match_score": round(platform_score, 4),
            "genre_match_score": round(genre_score, 4),
            "priority_score": round(priority_bonus, 4),
            "weight_score": round(weight, 4),
            "quality_score": round(quality_adjusted, 4),
            "effect_score": round(feedback_delta, 4),
            "risk_penalty": round(risk_penalty, 4),
            "status_penalty": round(status_penalty, 4),
            "source_policy_penalty": round(source_policy_penalty, 4),
        },
    }


def _select_pack_items(items: list[dict[str, Any]], *, flow: str, budget: dict[str, Any]) -> list[dict[str, Any]]:
    role_rank = {
        "required": 0,
        "review_rule": 0,
        "constraint": 1,
        "canon_context": 1,
        "style_constraint": 2,
        "optional": 3,
        "risk_warning": 4,
        "forbidden": 5,
    }
    ranked = sorted(
        items,
        key=lambda item: (
            role_rank.get(str(item.get("item_role") or "optional"), 3),
            -float(item.get("selection_score", 0.0) or 0.0),
            int(item.get("priority", 100) or 100),
            str(item.get("knowledge_id", "")),
        ),
    )
    max_items = int(budget.get("max_items", 0) or 0)
    if max_items > 0:
        ranked = ranked[:max_items]
    max_tokens = int(budget.get("max_estimated_tokens", 0) or budget.get("max_selector_tokens", 0) or 0)
    if max_tokens <= 0:
        return ranked
    selected: list[dict[str, Any]] = []
    used = 0
    for item in ranked:
        estimated = int(item.get("estimated_tokens", 1) or 1)
        if selected and used + estimated > max_tokens:
            continue
        selected.append(item)
        used += estimated
    return selected


def _quality_feedback_delta(storage: LocalStorage, knowledge_id: str, flow: str) -> float:
    if not knowledge_id:
        return 0.0
    rows = _list_assets(storage, "knowledge", "knowledge_quality_score", limit=500)
    deltas = [
        _float(row.get("content", {}).get("delta"), 0.0)
        for row in rows
        if str(row.get("content", {}).get("knowledge_id") or "") == knowledge_id
        and (not row.get("content", {}).get("flow") or str(row.get("content", {}).get("flow")) == flow)
    ]
    return round(max(-0.5, min(0.5, sum(deltas))), 4)


def _estimate_pack_item_tokens(item: dict[str, Any]) -> int:
    text = " ".join(
        str(item.get(key) or "")
        for key in ["concept_name", "core_explanation", "constraint_text", "output_form", "prompt_fragment"]
    )
    return max(1, int(len(text) / 4) + 1)


def _recency_bonus(asset: dict[str, Any]) -> float:
    value = str(asset.get("updated_at") or asset.get("created_at") or "")
    return 0.02 if value else 0.0


def _normalize_risk_level(value: str) -> str:
    normalized = str(value or "low").strip().lower()
    return normalized if normalized in {"low", "medium", "high", "critical"} else "low"


def _project_scope_matches(asset_project_id: str, requested_project_id: str) -> bool:
    requested = str(requested_project_id or "").strip()
    asset_project = str(asset_project_id or "").strip()
    if not requested or requested == "local-system":
        return True
    if not asset_project or asset_project == "local-system":
        return True
    return asset_project == requested


def _write_pack_item_assets(storage: LocalStorage, pack: KnowledgePack, items: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for index, item in enumerate(items):
        content = {
            "knowledge_pack_id": pack.id,
            "knowledge_id": item.get("knowledge_id", ""),
            "item_role": item.get("item_role", "optional"),
            "flow": pack.content.get("flow", ""),
            "priority": int(item.get("priority", 100) or 100),
            "payload": item,
        }
        asset = KnowledgePackItem(
            id=_stable_asset_id("knowledge_pack_item", pack.id, str(index + 1), str(item.get("knowledge_id", "")), str(item.get("binding_id", ""))),
            title=f"{pack.title} item {index + 1}",
            source=pack.id,
            tags=["mkaos", "knowledge-pack-item", content["flow"], content["item_role"]],
            content=content,
            metadata={
                "project_id": pack.metadata.get("project_id", "local-system"),
                "workspace_path": pack.metadata.get("workspace_path", ""),
                "mkaos": True,
                "use_in_generation_rag": False,
                "knowledge_pack_id": pack.id,
            },
            references=_dedupe([pack.id, str(item.get("knowledge_id", ""))]),
        )
        _ensure_valid(asset.to_dict())
        path = storage.write_asset("contexts", asset)
        paths.append(_display_path(storage.root, path))
    return paths


def _group_pack_items(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped = {role: [] for role in PACK_ITEM_ROLES}
    for item in items:
        grouped.setdefault(str(item.get("item_role") or "optional"), []).append(item)
    return grouped


def _pack_role_from_binding(content: dict[str, Any], flow: str) -> str:
    for key in ["input_role", "usage_type"]:
        value = str(content.get(key) or "")
        if value in PACK_ITEM_ROLES:
            return value
    if flow == "review":
        return "review_rule"
    if flow == "prose" and content.get("risk_level") in {"high", "critical"}:
        return "risk_warning"
    return "optional" if flow == "prose" else "required"


def _rule_payload(row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content", {})
    return {
        "rule_id": row.get("id", ""),
        "rule_name": content.get("rule_name", row.get("title", "")),
        "rule_type": content.get("rule_type", ""),
        "trigger_condition": content.get("trigger_condition", ""),
        "check_items": content.get("check_items", []),
        "severity": content.get("severity", "medium"),
        "blocking": bool(content.get("blocking", False)),
        "fix_suggestion": content.get("fix_suggestion", ""),
        "applicable_flows": content.get("applicable_flows", []),
    }


def _generation_constraints(flow: str, items: list[dict[str, Any]], rules: list[dict[str, Any]]) -> list[str]:
    values = [str(item.get("constraint_text", "")) for item in items if str(item.get("constraint_text", "")).strip()]
    values.extend([f"{rule.get('rule_name')}: {rule.get('fix_suggestion')}" for rule in rules if rule.get("fix_suggestion")])
    if flow == "prose":
        values.extend([
            "每章核心知识点不得超过 knowledge_budget.max_core_knowledge",
            "知识必须转成动作、对话、物件或场景变化",
            "禁止连续解释性段落",
            "禁止人物替作者讲课",
        ])
    return _dedupe(values)


def _style_constraints(flow: str, items: list[dict[str, Any]]) -> list[str]:
    if flow != "prose":
        return []
    return _dedupe([str(item.get("output_form", "")) for item in items if str(item.get("output_form", "")).strip()])


def _risk_warnings(items: list[dict[str, Any]]) -> list[str]:
    return _dedupe([f"{item.get('concept_name')}: {item.get('risk_level')}" for item in items if item.get("risk_level") in {"high", "critical"}])


def _knowledge_budget(flow: str, value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        max_core = int(value.get("max_core_knowledge", 3 if flow == "prose" else 8) or 0)
        max_optional = int(value.get("max_optional_knowledge", max_core * 2) or 0)
        max_tokens = int(value.get("max_estimated_tokens", value.get("max_selector_tokens", 0)) or 0)
    else:
        max_core = 3 if flow == "prose" else 8
        max_optional = max_core * 2
        max_tokens = 0
    return {
        "max_core_knowledge": max_core,
        "max_optional_knowledge": max_optional,
        "max_items": max(6, max_core + max_optional),
        "max_estimated_tokens": max_tokens,
        "anti_encyclopedia_required": flow == "prose",
        "source_chunk_raw_text_allowed": False,
    }


def _output_contract(flow: str) -> dict[str, Any]:
    contracts = {
        "outline": {"must_include": ["logic_constraints", "review_rule_refs"], "must_not_include": ["draft prose"]},
        "chapter_outline": {"must_include": ["goal", "obstacle", "action", "result", "information_change", "emotion", "hook"]},
        "prose": {"must_include": ["allowed_knowledge_points", "knowledge_budget"], "must_not_include": ["source_chunk.raw_text", "encyclopedia paragraphs"]},
        "review": {"must_include": ["rule_id", "rule_name", "severity", "blocking", "message", "fix_suggestion", "rollback_level"]},
        "revision": {"must_include": ["revision_constraints", "must_preserve", "target_issues"], "must_not_include": ["unbounded rewrite", "raw source text"]},
        "recap": {"must_include": ["continuity_risks", "memory_update_package", "review_issue_inputs"], "must_not_include": ["source_chunk.raw_text", "draft-only hidden context"]},
        "publish": {"must_include": ["blocking_status", "known_risks", "platform_checklist"], "must_not_include": ["source_chunk.raw_text", "unchecked blocking issues"]},
        "feedback": {"must_include": ["feedback_signal", "affected_assets", "weight_update_candidate"], "must_not_include": ["direct mutation without human gate", "raw reader private data"]},
    }
    return contracts.get(flow, {"must_include": ["knowledge_pack_id", "pack_items"], "must_not_include": ["source_chunk.raw_text"]})


def _canon_context(storage: LocalStorage, project_id: str) -> dict[str, Any]:
    rows = _list_assets(storage, "continuity", "canon_database", project_id=project_id if project_id != "local-system" else None, limit=20)
    facts: list[Any] = []
    entities: list[Any] = []
    rules: list[Any] = []
    arcs: list[Any] = []
    foreshadowing: list[Any] = []
    characters: list[Any] = []
    refs: list[str] = []
    for row in rows:
        content = row.get("content", {})
        facts.extend(content.get("facts", []) if isinstance(content.get("facts", []), list) else [])
        entities.extend(content.get("entities", []) if isinstance(content.get("entities", []), list) else [])
        rules.extend(content.get("rules", []) if isinstance(content.get("rules", []), list) else [])
        refs.append(row.get("path", ""))
    checked_asset_types = ["canon_database"] if rows else []
    for row in _list_assets(storage, "characters", "character_card", project_id=project_id if project_id != "local-system" else None, limit=100):
        content = row.get("content", {})
        characters.append({
            "entity": content.get("canonical_name") or content.get("name") or row.get("title"),
            "canonical_name": content.get("canonical_name") or content.get("name") or row.get("title"),
            "status": content.get("status") or content.get("state") or row.get("status") or "",
            "role": content.get("role", ""),
            "source_asset_id": row.get("id", ""),
            "source_asset_path": row.get("path", ""),
            "canon_dimension": "character",
        })
        refs.append(row.get("path", ""))
    if characters:
        checked_asset_types.append("character_card")
    for row in _list_assets(storage, "continuity", "character_state_ledger", project_id=project_id if project_id != "local-system" else None, limit=50):
        for character in row.get("content", {}).get("characters", []) if isinstance(row.get("content", {}).get("characters", []), list) else []:
            if isinstance(character, dict):
                characters.append({**character, "source_asset_id": row.get("id", ""), "source_asset_path": row.get("path", ""), "canon_dimension": "character"})
        refs.append(row.get("path", ""))
    for row in _list_assets(storage, "continuity", "fact_ledger", project_id=project_id if project_id != "local-system" else None, limit=50):
        for fact in row.get("content", {}).get("facts", []) if isinstance(row.get("content", {}).get("facts", []), list) else []:
            if isinstance(fact, dict):
                facts.append({**fact, "source_asset_id": row.get("id", ""), "source_asset_path": row.get("path", ""), "canon_dimension": "fact"})
        refs.append(row.get("path", ""))
    for row in _list_assets(storage, "continuity", "arc_plan", project_id=project_id if project_id != "local-system" else None, limit=50):
        content = row.get("content", {})
        arcs.append({**content, "entity": content.get("arc_id") or content.get("title") or row.get("title"), "source_asset_id": row.get("id", ""), "source_asset_path": row.get("path", ""), "canon_dimension": "arc"})
        refs.append(row.get("path", ""))
    if arcs:
        checked_asset_types.append("arc_plan")
    for row in _list_assets(storage, "continuity", "foreshadowing_thread", project_id=project_id if project_id != "local-system" else None, limit=100):
        content = row.get("content", {})
        foreshadowing.append({**content, "entity": content.get("thread_id") or content.get("setup") or row.get("title"), "source_asset_id": row.get("id", ""), "source_asset_path": row.get("path", ""), "canon_dimension": "foreshadowing"})
        refs.append(row.get("path", ""))
    if foreshadowing:
        checked_asset_types.append("foreshadowing_thread")
    for row in _list_assets(storage, "continuity", "continuity_bible", project_id=project_id if project_id != "local-system" else None, limit=20):
        content = row.get("content", {})
        entities.extend(content.get("entities", []) if isinstance(content.get("entities", []), list) else [])
        rules.extend(content.get("worldview_rules", []) if isinstance(content.get("worldview_rules", []), list) else [])
        rules.extend(content.get("constraints", []) if isinstance(content.get("constraints", []), list) else [])
        refs.append(row.get("path", ""))
    for row in _list_assets(storage, "continuity", "power_scale_rule", project_id=project_id if project_id != "local-system" else None, limit=50):
        content = row.get("content", {})
        rules.append({**content, "source_asset_id": row.get("id", ""), "source_asset_path": row.get("path", ""), "canon_dimension": "world_rule"})
        refs.append(row.get("path", ""))
    if rules:
        checked_asset_types.append("world_rule")
    source = "canon_asset_context" if checked_asset_types else "stub"
    warnings = [] if checked_asset_types else ["canon_database not found; stub used"]
    return {
        "source": source,
        "facts": facts,
        "entities": entities,
        "characters": characters,
        "arcs": arcs,
        "foreshadowing": foreshadowing,
        "rules": rules,
        "references": _dedupe(refs),
        "checked_asset_types": _dedupe(checked_asset_types),
        "warnings": warnings,
    }


def _canon_conflict_check_input(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or "local-system")
    project_canon = _canon_context(storage, project_id)
    canon = _merge_canon_context(project_canon, payload.get("canon") if isinstance(payload.get("canon"), dict) else {})
    if isinstance(payload.get("characters"), list):
        canon = {**canon, "characters": [*canon.get("characters", []), *payload["characters"]]}
    if isinstance(payload.get("arcs"), list):
        canon = {**canon, "arcs": [*canon.get("arcs", []), *payload["arcs"]]}
    if isinstance(payload.get("foreshadowing"), list):
        canon = {**canon, "foreshadowing": [*canon.get("foreshadowing", []), *payload["foreshadowing"]]}
    if isinstance(payload.get("world_rules"), list):
        canon = {**canon, "rules": [*canon.get("rules", []), *payload["world_rules"]]}
    return {
        "project_id": project_id,
        "target_asset_id": str(payload.get("target_asset_id") or payload.get("artifact_id") or ""),
        "target_asset_type": str(payload.get("target_asset_type") or payload.get("artifact_type") or "artifact"),
        "artifact_text": str(payload.get("artifact_text") or payload.get("text") or ""),
        "claims": payload.get("claims", []) if isinstance(payload.get("claims", []), list) else [],
        "canon": canon,
    }


def _merge_canon_context(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = {**base, **{key: value for key, value in override.items() if key not in {"facts", "entities", "characters", "arcs", "foreshadowing", "rules", "references", "checked_asset_types"}}}
    for key in ["facts", "entities", "characters", "arcs", "foreshadowing", "rules", "references", "checked_asset_types"]:
        values: list[Any] = []
        values.extend(base.get(key, []) if isinstance(base.get(key, []), list) else [])
        values.extend(override.get(key, []) if isinstance(override.get(key, []), list) else [])
        merged[key] = _dedupe(values) if all(isinstance(item, str) for item in values) else values
    if override.get("source"):
        merged["source"] = f"{base.get('source', 'stub')}+payload"
    return merged


def _canon_facts(canon: dict[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for key, dimension in [
        ("facts", "fact"),
        ("entities", "canon"),
        ("characters", "character"),
        ("arcs", "arc"),
        ("foreshadowing", "foreshadowing"),
    ]:
        for item in canon.get(key, []) if isinstance(canon.get(key, []), list) else []:
            if isinstance(item, dict):
                facts.append({**item, "canon_dimension": item.get("canon_dimension") or dimension})
    return facts


def _canon_fact_name(fact: dict[str, Any]) -> str:
    for key in ["entity", "canonical_name", "name", "title", "arc_id", "thread_id", "fact_id"]:
        value = str(fact.get(key) or "").strip()
        if value:
            return value
    return ""


def _canon_fact_value(fact: dict[str, Any], key: str) -> str:
    for candidate in [key, "status", "state", "value"]:
        value = str(fact.get(candidate) or "").strip()
        if value:
            return value
    return ""


def _canon_evidence_refs(fact: dict[str, Any], canon: dict[str, Any]) -> list[str]:
    refs = [str(fact.get("source_asset_id") or ""), str(fact.get("source_asset_path") or "")]
    refs.extend(str(ref) for ref in canon.get("references", []) if str(ref).strip())
    return _dedupe([ref for ref in refs if ref])


def _canon_issue(message: str, fix_suggestion: str, *, dimension: str, evidence_refs: list[str]) -> dict[str, Any]:
    issue = _issue("rule_canon_conflict", "Canon 冲突检查", "critical", True, message, fix_suggestion, "artifact")
    issue.update({
        "issue_type": "canon_conflict",
        "source_system": "mkaos.canon_conflict",
        "dimension": dimension,
        "evidence_refs": evidence_refs,
    })
    return issue


def _anti_encyclopedia_issues(storage: LocalStorage, text: str) -> list[dict[str, Any]]:
    if not text.strip():
        return []
    rules = ensure_default_rule_cards(storage)
    rule_id = next((row.get("id", "") for row in rules if row.get("content", {}).get("rule_type") == "anti_encyclopedia"), "rule_anti_encyclopedia")
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    explanation_keywords = ["制度", "本质", "所谓", "因此", "导致", "概念", "规则", "税源", "土地兼并", "专业上", "定义", "自由", "心理", "机制", "灵脉", "番茄", "节奏"]
    explanatory = [
        index
        for index, paragraph in enumerate(paragraphs)
        if len(paragraph) >= 12 and any(keyword in paragraph for keyword in explanation_keywords) and not _has_scene_or_dialogue(paragraph)
    ]
    issues: list[dict[str, Any]] = []
    if len(explanatory) >= 2 and any(b == a + 1 for a, b in zip(explanatory, explanatory[1:])):
        issues.append(_issue(rule_id, "反百科化检查", "high", False, "正文存在连续解释性段落，知识停留在说明层。", "改写为动作、对话、物件或场景变化。", "paragraph"))
    elif explanatory:
        issues.append(_issue(rule_id, "反百科化检查", "high", False, "正文存在明显解释性段落，知识没有场景化。", "至少加入行动、证物、对话或场景状态变化。", "paragraph"))
    if re.search(r"[“\"].{0,20}(你要知道|所谓|本质上|制度就是|专业上).{10,}[”\"]", text):
        issues.append(_issue(rule_id, "反百科化检查", "high", False, "人物对话承担作者讲课功能。", "把信息拆成冲突中的追问、隐瞒、证物或误解。", "dialogue"))
    if "土地兼并" in text and not any(term in text for term in ["田契", "县衙", "粮仓", "佃户", "豪强", "税银", "案卷"]):
        issues.append(_issue(rule_id, "反百科化检查", "medium", False, "制度知识没有落到可见物件或场景。", "用田契、县衙、粮仓、佃户等载体承载知识。", "scene"))
    return issues


def _knowledge_usage_issues(storage: LocalStorage, payload: dict[str, Any]) -> list[dict[str, Any]]:
    pack_ref = str(payload.get("knowledge_pack_id") or payload.get("knowledge_pack_path") or "")
    if not pack_ref:
        return []
    try:
        pack = get_knowledge_pack(storage, pack_ref)["asset"]
    except FileNotFoundError:
        return [_issue("rule_knowledge_usage", "知识有效性检查", "high", False, "声明的 Knowledge Pack 不存在。", "重新构造 Knowledge Pack 并记录 usage event。", "artifact")]
    if pack.get("content", {}).get("flow") == "prose" and "raw_text" in str(pack.get("content", {})):
        return [_issue("rule_source_isolation", "知识有效性检查", "critical", True, "prose Knowledge Pack 包含 source chunk raw_text。", "重建 pack，仅保留 source_chunk_ids 和抽象知识。", "artifact")]
    return []


def _artifact_text(storage: LocalStorage, payload: dict[str, Any]) -> str:
    if payload.get("artifact_text") or payload.get("text"):
        return str(payload.get("artifact_text") or payload.get("text") or "")
    path = payload.get("artifact_path") or payload.get("path")
    if path:
        try:
            data = storage.read_json(resolve_path(storage.root, path))
            content = data.get("content", {}) if isinstance(data, dict) and isinstance(data.get("content", {}), dict) else {}
            return str(content.get("text") or content.get("summary") or content)
        except Exception:
            return ""
    return ""


def _record_quality_score(storage: LocalStorage, *, knowledge_id: str, flow: str, delta: float, reason: str, metadata: dict[str, Any]) -> dict[str, Any]:
    score_id = make_id("knowledge_quality_score", f"{knowledge_id}-{flow}-{reason}-{utc_now()}")
    try:
        _, knowledge = _find_asset(storage, knowledge_id, asset_type="knowledge_card", categories=["knowledge"])
        knowledge_meta = knowledge.get("metadata", {}) if isinstance(knowledge.get("metadata", {}), dict) else {}
    except FileNotFoundError:
        knowledge_meta = {}
    project_id = str(metadata.get("project_id") or knowledge_meta.get("project_id") or "local-system")
    workspace_path = str(metadata.get("workspace_path") or knowledge_meta.get("workspace_path") or "")
    os_envelope_meta = envelope_asset_metadata(metadata.get("os_envelope") if isinstance(metadata.get("os_envelope"), dict) else {})
    content = {
        "score_id": score_id,
        "knowledge_id": knowledge_id,
        "flow": flow if flow in MKAOS_FLOWS else "",
        "delta": float(delta),
        "reason": reason,
        "created_at": utc_now(),
        "metadata": metadata,
    }
    asset = KnowledgeQualityScore(
        id=score_id,
        title=f"Quality score {knowledge_id} {delta:+.2f}",
        source=knowledge_id,
        tags=["mkaos", "knowledge-quality-score", flow],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "mkaos": True, "use_in_generation_rag": False, "delta": delta, **os_envelope_meta},
        references=[knowledge_id],
    )
    _ensure_valid(asset.to_dict())
    path = storage.write_asset("knowledge", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _feedback_delta(payload: dict[str, Any]) -> float:
    delta = _float(payload.get("delta"), 0.0)
    if payload.get("review_passed") and payload.get("human_confirmed_effective"):
        delta += 0.05
    if payload.get("conflict_effective"):
        delta += 0.10
    if payload.get("anti_encyclopedia_hit") and str(payload.get("flow") or "") == "prose":
        delta -= 0.15
    if payload.get("canon_conflict_hit"):
        delta -= 0.25
    return round(delta, 4)


def _low_effect_event_count(storage: LocalStorage, knowledge_id: str, flow: str) -> int:
    events = [
        row
        for row in list_usage_events(storage, flow=flow if flow in MKAOS_FLOWS else None, limit=1000)
        if str(row.get("content", {}).get("knowledge_id", "")) == knowledge_id
    ]
    low = [row for row in events[-3:] if _float(row.get("content", {}).get("effect_score"), 1.0) < 0.2]
    return len(low)


def _find_asset(storage: LocalStorage, ref: str | Path, *, asset_type: str | None = None, categories: list[str] | None = None) -> tuple[Path, dict[str, Any]]:
    value = str(ref)
    if not value:
        raise FileNotFoundError("empty asset reference")
    if "/" in value or value.endswith(".json"):
        path = resolve_path(storage.root, value)
        data = storage.read_json(path)
        if isinstance(data, dict) and (not asset_type or data.get("type") == asset_type):
            return path, data
    for category in categories or ["raw", "knowledge", "quality_standards", "templates", "contexts", "runs", "continuity"]:
        for path in reversed(storage.list_json(category)):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if asset_type and data.get("type") != asset_type:
                continue
            if value in {str(data.get("id", "")), str(path.relative_to(storage.root))}:
                return path, data
    raise FileNotFoundError(f"asset not found: {ref}")


def _find_existing_source_chunk(storage: LocalStorage, source_id: str, content_hash: str) -> dict[str, Any] | None:
    for row in _list_assets(storage, "raw", "source_chunk", limit=2000):
        content = row.get("content", {})
        if str(content.get("source_document_id", "")) == source_id and str(content.get("content_hash", "")) == content_hash:
            return row
    return None


def _list_assets(storage: LocalStorage, category: str, asset_type: str, *, project_id: str | None = None, mkaos_only: bool | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json(category)):
        if len(rows) >= limit:
            break
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != asset_type:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        record_project = str(metadata.get("project_id") or content.get("project_id") or "")
        if project_id and record_project and record_project != project_id:
            continue
        if mkaos_only is True and not (metadata.get("mkaos") or content.get("mkaos_source")):
            continue
        rows.append(_asset_row(storage, path, data))
    return rows


def _asset_row(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    return {
        "path": _display_path(storage.root, path),
        "id": data.get("id", ""),
        "type": data.get("type", ""),
        "title": data.get("title") or data.get("name", ""),
        "source": data.get("source", ""),
        "tags": data.get("tags", []),
        "project_id": metadata.get("project_id") or content.get("project_id") or "",
        "workspace_path": metadata.get("workspace_path") or content.get("workspace_path") or "",
        "status": content.get("status") or metadata.get("asset_status") or "",
        "risk_level": content.get("risk_level") or metadata.get("risk_level") or "",
        "content": content,
        "metadata": metadata,
        "updated_at": data.get("updated_at", ""),
        "asset": data,
    }


def _ensure_valid(data: dict[str, Any]) -> None:
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))


def _hash_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _stable_asset_id(prefix: str, *parts: str) -> str:
    seed = "|".join(str(part) for part in parts if str(part).strip()) or prefix
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", seed.strip().lower()).strip("-")[:96] or prefix
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]
    return f"{prefix.replace('_', '-')}-{slug}-{digest}"


def _valid_flow(flow: str) -> str:
    if flow not in MKAOS_FLOWS:
        raise ValueError("flow must be outline, chapter_outline, prose, review, revision, recap, publish, or feedback")
    return flow


def _strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except Exception:
        return fallback


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _display_path(root: Path, path: str | Path) -> str:
    candidate = Path(path)
    try:
        return str(candidate.relative_to(root))
    except ValueError:
        return str(candidate)


def _knowledge_status(data: dict[str, Any]) -> str:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    return str(content.get("status") or metadata.get("asset_status") or "active")


def _default_usage_type(flow: str) -> str:
    return {
        "outline": "required",
        "chapter_outline": "required",
        "prose": "optional",
        "review": "review_rule",
        "revision": "revision_constraint",
        "recap": "recap_control",
        "publish": "publish_gate",
        "feedback": "feedback_signal",
    }[flow]


def _default_input_role(flow: str) -> str:
    return {
        "outline": "required",
        "chapter_outline": "required",
        "prose": "optional",
        "review": "review_rule",
        "revision": "revision_constraint",
        "recap": "recap_memory",
        "publish": "risk_check",
        "feedback": "weight_signal",
    }[flow]


def _default_output_form(flow: str) -> str:
    return {
        "outline": "logic constraint",
        "chapter_outline": "scene conflict",
        "prose": "action/dialogue/object/scene",
        "review": "review issue contract",
        "revision": "revision constraint",
        "recap": "longform stability memory",
        "publish": "publish gate risk item",
        "feedback": "selection weight signal",
    }[flow]


def _genre_matches(values: Any, genre: str) -> bool:
    rows = _strings(values)
    return not genre or not rows or genre in rows or "all" in {item.lower() for item in rows} or "通用" in rows


def _platform_matches(values: Any, platform: str) -> bool:
    rows = _strings(values)
    return not platform or not rows or platform in rows or "all" in {item.lower() for item in rows} or "通用" in rows


def _concept_names(content: dict[str, Any]) -> list[str]:
    return _dedupe([item.get("concept_name", "") for item in [*content.get("required_knowledge", []), *content.get("optional_knowledge", [])]])


def _rule_names(rules: list[dict[str, Any]], rule_types: set[str]) -> list[dict[str, Any]]:
    return [
        {
            "rule_id": rule.get("rule_id", ""),
            "rule_name": rule.get("rule_name", ""),
            "severity": rule.get("severity", ""),
            "blocking": rule.get("blocking", False),
            "fix_suggestion": rule.get("fix_suggestion", ""),
        }
        for rule in rules
        if str(rule.get("rule_type", "")) in rule_types
    ]


def _allowed_terms(item: dict[str, Any]) -> list[str]:
    aliases = item.get("concept_aliases", []) if isinstance(item.get("concept_aliases", []), list) else []
    terms = [str(item.get("concept_name", "")), *[str(alias) for alias in aliases]]
    if "土地兼并" in terms:
        terms.extend(["田契", "县衙", "粮仓", "佃户"])
    return _dedupe(terms)


def _has_scene_or_dialogue(paragraph: str) -> bool:
    return any(mark in paragraph for mark in ["“", "”", "\"", "抬", "走", "拿", "递", "看", "听", "门", "雨", "血", "案卷", "田契", "县衙", "粮仓"])


def _issue(rule_id: str, rule_name: str, severity: str, blocking: bool, message: str, fix_suggestion: str, rollback_level: str) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "rule_name": rule_name,
        "severity": severity,
        "blocking": blocking,
        "message": message,
        "fix_suggestion": fix_suggestion,
        "rollback_level": rollback_level,
    }


def _severity_penalty(severity: str) -> int:
    return {"critical": 45, "high": 25, "medium": 12, "low": 5, "info": 1}.get(str(severity), 5)


def _looks_like_broken_causality(text: str) -> bool:
    return any(term in text for term in ["突然成功", "莫名解决", "无缘无故"]) or ("结果" in text and not any(term in text for term in ["因为", "于是", "只好", "代价", "选择"]))


def _risk_reasons(row: dict[str, Any], risky_ids: set[str]) -> list[str]:
    reasons: list[str] = []
    content = row.get("content", {})
    metadata = row.get("metadata", {})
    if content.get("status") == "deprecated" or metadata.get("asset_status") == "deprecated":
        reasons.append("deprecated")
    if content.get("status") == "needs_review" or metadata.get("asset_status") == "needs_review":
        reasons.append("needs_review")
    if content.get("risk_level") in {"high", "critical"} or metadata.get("risk_level") in {"high", "critical"}:
        reasons.append("high_risk")
    if row.get("id") in risky_ids:
        reasons.append("review_hit")
    return reasons


def _payload_project_id(*payloads: dict[str, Any]) -> str:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata", {}), dict) else {}
        content = payload.get("content", {}) if isinstance(payload.get("content", {}), dict) else {}
        value = str(metadata.get("project_id") or content.get("project_id") or payload.get("project_id") or "")
        if value:
            return value
    return "local-system"


def _find_version_asset(storage: LocalStorage, version_ref: str) -> dict[str, Any]:
    for asset_type in ["knowledge_version", "rule_version", "template_version", "pack_snapshot_version", "selector_policy_version"]:
        try:
            _, data = _find_asset(storage, version_ref, asset_type=asset_type, categories=["knowledge"])
            return data
        except FileNotFoundError:
            continue
    raise FileNotFoundError(f"version not found: {version_ref}")


def _pack_budget_usage(content: dict[str, Any]) -> dict[str, Any]:
    items = content.get("pack_items", []) if isinstance(content.get("pack_items", []), list) else []
    estimated = sum(int(item.get("estimated_tokens", 0) or 0) for item in items if isinstance(item, dict))
    budget = content.get("knowledge_budget", {}) if isinstance(content.get("knowledge_budget", {}), dict) else {}
    return {
        "selected_count": len(items),
        "estimated_tokens": estimated,
        "max_items": budget.get("max_items", 0),
        "max_core_knowledge": budget.get("max_core_knowledge", 0),
        "over_budget": bool(budget.get("max_estimated_tokens") and estimated > int(budget.get("max_estimated_tokens") or 0)),
    }


def _copyright_risk_result(items: list[dict[str, Any]]) -> dict[str, Any]:
    high = []
    for item in items:
        dimensions = item.get("quality_dimensions") if isinstance(item.get("quality_dimensions"), dict) else {}
        if _float(dimensions.get("copyright_risk_score"), 0.0) >= 0.7 or item.get("risk_level") in {"high", "critical"}:
            high.append({"knowledge_id": item.get("knowledge_id", ""), "risk_level": item.get("risk_level", ""), "copyright_risk_score": dimensions.get("copyright_risk_score", 0.0)})
    return {"high_risk_count": len(high), "high_risk_items": high, "raw_text_included": False}


def _source_kind_policy(source_kind: str) -> dict[str, Any]:
    defaults = {
        "professional_book": {
            "cleaning_policy": "strict_evidence_only",
            "chunk_policy": "semantic_short_chunks",
            "copyright_boundary": "operator evidence only; abstract extraction required",
            "allow_downstream_generation": False,
            "default_disciplines": ["专业知识"],
            "recommended_extraction": ["knowledge_card_candidate", "rule_card_candidate"],
        },
        "webnovel_analysis": {
            "cleaning_policy": "analysis_only",
            "chunk_policy": "pattern_chunks",
            "copyright_boundary": "abstract craft pattern only; no protected expression",
            "allow_downstream_generation": False,
            "default_disciplines": ["叙事学"],
            "recommended_extraction": ["template_card_candidate", "rule_card_candidate"],
        },
        "classic_novel_analysis": {
            "cleaning_policy": "literary_analysis_only",
            "chunk_policy": "theme_scene_mechanism",
            "copyright_boundary": "public analysis abstraction; no expression reuse",
            "allow_downstream_generation": False,
            "default_disciplines": ["文学"],
            "recommended_extraction": ["knowledge_card_candidate"],
        },
        "platform_rule": {
            "cleaning_policy": "rules",
            "chunk_policy": "rule_chunks",
            "copyright_boundary": "platform policy summarized as constraints",
            "allow_downstream_generation": False,
            "default_disciplines": ["平台策略"],
            "recommended_extraction": ["rule_card_candidate", "template_card_candidate"],
        },
        "reader_feedback": {
            "cleaning_policy": "privacy_minimized",
            "chunk_policy": "feedback_signals",
            "copyright_boundary": "reader signal only",
            "allow_downstream_generation": False,
            "default_disciplines": ["读者反馈"],
            "recommended_extraction": ["feedback_attribution"],
        },
        "agent_report": {
            "cleaning_policy": "asset_report",
            "chunk_policy": "report_sections",
            "copyright_boundary": "internal agent report",
            "allow_downstream_generation": False,
            "default_disciplines": ["工程审稿"],
            "recommended_extraction": ["rule_card_candidate"],
        },
    }
    return defaults.get(
        source_kind,
        {
            "cleaning_policy": "manual_note",
            "chunk_policy": "paragraph",
            "copyright_boundary": "manual note for abstract extraction",
            "allow_downstream_generation": False,
            "default_disciplines": ["general"],
            "recommended_extraction": ["knowledge_card_candidate"],
        },
    )


def _parse_professional_book_input(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    explicit_text = str(payload.get("text") or payload.get("content") or "")
    file_path = str(payload.get("file_path") or payload.get("path") or "").strip()
    source_format = str(payload.get("source_format") or payload.get("format") or "").strip().lower()
    parser_report = {
        "parser_id": "mkaos.professional_book_parser.v1",
        "source_format": source_format or "text",
        "status": "parsed",
        "warnings": [],
        "optional_dependency_required": "",
        "file_path": file_path,
    }
    text = explicit_text
    if not text and file_path:
        path = Path(file_path)
        if not path.is_absolute():
            path = Path(storage.root) / file_path
        suffix = path.suffix.lower().lstrip(".")
        source_format = source_format or suffix or "text"
        parser_report["source_format"] = source_format
        text, file_warnings, dependency = _read_professional_book_file(path, source_format)
        parser_report["warnings"].extend(file_warnings)
        parser_report["optional_dependency_required"] = dependency
        parser_report["status"] = "parsed" if text else "unsupported_or_empty"
    sections = _parse_markdown_or_book_sections(text, source_format=source_format or parser_report["source_format"])
    parser_report["section_count"] = len(sections)
    parser_report["text_hash"] = _hash_text(text)
    parser_report["source_isolation"] = {"raw_text_included": False, "clean_text_included": False, "parser_report_hash_only": True}
    return {"text": text, "sections": sections, "parser_report": parser_report}


def _read_professional_book_file(path: Path, source_format: str) -> tuple[str, list[str], str]:
    warnings: list[str] = []
    dependency = ""
    if not path.exists():
        return "", [f"file not found: {path}"], ""
    if source_format in {"txt", "text", "md", "markdown"}:
        return path.read_text(encoding="utf-8"), warnings, ""
    if source_format == "pdf":
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception:
            return "", ["PDF parser unavailable; install optional dependency pypdf to parse PDF files"], "pypdf"
        reader = PdfReader(str(path))
        pages = [(page.extract_text() or "") for page in reader.pages]
        return "\n\n".join(pages), warnings, ""
    if source_format == "docx":
        try:
            import docx  # type: ignore
        except Exception:
            return "", ["DOCX parser unavailable; install optional dependency python-docx to parse DOCX files"], "python-docx"
        document = docx.Document(str(path))
        return "\n\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()), warnings, ""
    if source_format == "epub":
        try:
            from ebooklib import epub  # type: ignore
        except Exception:
            return "", ["EPUB parser unavailable; install optional dependency ebooklib to parse EPUB files"], "ebooklib"
        book = epub.read_epub(str(path))
        parts: list[str] = []
        for item in book.get_items():
            if hasattr(item, "get_content"):
                raw = item.get_content()
                if isinstance(raw, bytes):
                    parts.append(re.sub(r"<[^>]+>", " ", raw.decode("utf-8", errors="ignore")))
        return "\n\n".join(parts), warnings, ""
    return "", [f"unsupported professional book source_format: {source_format}"], ""


def _parse_markdown_or_book_sections(text: str, *, source_format: str) -> list[dict[str, Any]]:
    lines = str(text or "").splitlines()
    sections: list[dict[str, Any]] = []
    current_title = "Front Matter"
    current_level = 1
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_lines
        body = clean_source_text("\n".join(current_lines))
        if body:
            sections.append(
                {
                    "section_index": len(sections),
                    "title": current_title,
                    "level": current_level,
                    "text": body,
                    "page_start": None,
                    "page_end": None,
                    "chapter_title": current_title if current_level <= 2 else "",
                    "section_title": current_title,
                    "source_format": source_format or "text",
                }
            )
        current_lines = []

    heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")
    chapter_pattern = re.compile(r"^\s*(第[一二三四五六七八九十百千万\d]+[章节篇卷部].*|chapter\s+\d+.*)$", re.IGNORECASE)
    for line in lines:
        stripped = line.strip()
        heading = heading_pattern.match(stripped)
        chapter = chapter_pattern.match(stripped)
        if heading or chapter:
            flush()
            if heading:
                current_level = len(heading.group(1))
                current_title = heading.group(2).strip()
            else:
                current_level = 1
                current_title = stripped
            continue
        current_lines.append(line)
    flush()
    if not sections and text.strip():
        sections.append(
            {
                "section_index": 0,
                "title": "Professional Book",
                "level": 1,
                "text": clean_source_text(text),
                "page_start": None,
                "page_end": None,
                "chapter_title": "Professional Book",
                "section_title": "Professional Book",
                "source_format": source_format or "text",
            }
        )
    return sections


def _section_aware_chunks(sections: list[dict[str, Any]], *, target_chars: int) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for section in sections:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", str(section.get("text") or "")) if part.strip()]
        current: list[str] = []
        current_len = 0
        paragraph_start = 0
        for index, paragraph in enumerate(paragraphs):
            if current and current_len + len(paragraph) > target_chars:
                chunk_text = "\n\n".join(current)
                chunks.append(_structured_chunk(section, chunk_text, len(chunks), paragraph_start, index - 1))
                current = []
                current_len = 0
                paragraph_start = index
            current.append(paragraph)
            current_len += len(paragraph)
        if current:
            chunks.append(_structured_chunk(section, "\n\n".join(current), len(chunks), paragraph_start, paragraph_start + len(current) - 1))
    return chunks


def _structured_chunk(section: dict[str, Any], text: str, chunk_index: int, paragraph_start: int, paragraph_end: int) -> dict[str, Any]:
    return {
        "chunk_index": chunk_index,
        "text": text,
        "section_index": int(section.get("section_index", 0) or 0),
        "section_title": str(section.get("section_title") or section.get("title") or ""),
        "chapter_title": str(section.get("chapter_title") or section.get("title") or ""),
        "page_start": section.get("page_start"),
        "page_end": section.get("page_end"),
        "paragraph_start": paragraph_start,
        "paragraph_end": paragraph_end,
        "content_hash": _hash_text(text),
    }


def _replace_source_chunks_with_sections(storage: LocalStorage, source_ref: str | Path, structured_chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_path, source = _find_asset(storage, source_ref, asset_type="source_document", categories=["raw"])
    source_id = str(source.get("id") or "")
    project_id = str(source.get("metadata", {}).get("project_id") or "local-system")
    workspace_path = str(source.get("metadata", {}).get("workspace_path") or "")
    source_rel = _display_path(storage.root, source_path)
    written: list[dict[str, Any]] = []
    for chunk in structured_chunks:
        chunk_text = str(chunk.get("text") or "")
        asset = SourceChunk(
            title=f"{source.get('title') or source_id} {chunk.get('section_title') or 'section'} chunk {int(chunk.get('chunk_index', 0)) + 1}",
            source=source_id,
            tags=["mkaos", "source-chunk", "professional-book", "section-aware", f"chunk-{int(chunk.get('chunk_index', 0)) + 1}"],
            content={
                "source_document_id": source_id,
                "source_document_path": source_rel,
                "chunk_index": int(chunk.get("chunk_index", 0) or 0),
                "raw_text": chunk_text,
                "clean_text": chunk_text,
                "content_hash": str(chunk.get("content_hash") or _hash_text(chunk_text)),
                "clean_status": "cleaned",
                "section_aware": True,
                "section_index": chunk.get("section_index"),
                "section_title": chunk.get("section_title"),
                "chapter_title": chunk.get("chapter_title"),
                "page_start": chunk.get("page_start"),
                "page_end": chunk.get("page_end"),
                "paragraph_start": chunk.get("paragraph_start"),
                "paragraph_end": chunk.get("paragraph_end"),
            },
            metadata={
                "project_id": project_id,
                "workspace_path": workspace_path,
                "mkaos": True,
                "use_in_generation_rag": False,
                "content_hash": str(chunk.get("content_hash") or _hash_text(chunk_text)),
                "source_asset_path": source_rel,
                "evidence_layer_only": True,
                "section_aware": True,
            },
            references=[source_id, source_rel],
        )
        asset.id = _stable_asset_id("source_chunk", source_id, str(chunk.get("chunk_index", 0)), str(chunk.get("content_hash") or ""))
        path = storage.write_asset("raw", asset)
        written.append(_asset_row(storage, path, storage.read_json(path)))
    content = source.get("content", {}) if isinstance(source.get("content"), dict) else {}
    source["content"] = {
        **content,
        "structured_chunk_count": len(written),
        "structured_section_count": len({str(item.get("content", {}).get("section_index") or "") for item in written}),
        "professional_book_import_ready": True,
        "last_section_chunked_at": utc_now(),
    }
    source["updated_at"] = utc_now()
    storage.write_json(source_path, source)
    return written


def _create_spans_for_structured_chunks(storage: LocalStorage, chunks: list[dict[str, Any]], project_id: str) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for row in chunks:
        content = row.get("content", {}) if isinstance(row.get("content"), dict) else {}
        spans.append(
            create_evidence_span(
                storage,
                str(row.get("id") or ""),
                {
                    "project_id": project_id,
                    "page_start": content.get("page_start"),
                    "page_end": content.get("page_end"),
                    "chapter_title": content.get("chapter_title"),
                    "section_title": content.get("section_title"),
                    "paragraph_start": content.get("paragraph_start"),
                    "paragraph_end": content.get("paragraph_end"),
                    "extractor_id": "mkaos.professional_book_import",
                    "extraction_method": "section_aware_deterministic",
                },
            )
        )
    return spans


def _run_professional_book_batch_extraction(
    storage: LocalStorage,
    project_id: str,
    chunks: list[dict[str, Any]],
    spans: list[dict[str, Any]],
    payload: dict[str, Any],
) -> dict[str, Any]:
    limit = int(payload.get("max_extraction_chunks", 30) or 30)
    selected_chunks = chunks[:limit]
    candidates: list[dict[str, Any]] = []
    section_reports: list[dict[str, Any]] = []
    for row in selected_chunks:
        content = row.get("content", {}) if isinstance(row.get("content"), dict) else {}
        goal = _professional_book_extraction_goal(content)
        result = extract_knowledge_candidates(
            storage,
            {
                **payload,
                "project_id": project_id,
                "source_chunk_ids": [str(row.get("id") or "")],
                "extraction_goal": goal,
                "target_disciplines": _professional_book_disciplines(content),
                "target_flows": ["outline", "chapter_outline", "prose", "review"],
                "limit": 1,
                "provider_mode": payload.get("provider_mode") or "local_deterministic",
                "provider_opt_in": bool(payload.get("provider_opt_in", False)),
            },
        )
        candidates.extend(result.get("candidates", []))
        section_reports.append(
            {
                "source_chunk_id": row.get("id", ""),
                "section_title": content.get("section_title", ""),
                "candidate_count": len(result.get("candidates", [])),
                "provider": result.get("provider", {}),
            }
        )
    extraction_run = {
        "extraction_run_id": _stable_asset_id("professional_book_extraction_run", project_id, str(len(selected_chunks)), str(len(candidates))),
        "selected_chunk_count": len(selected_chunks),
        "candidate_count": len(candidates),
        "section_reports": section_reports,
        "evidence_span_ids": [str(span.get("asset", {}).get("id") or "") for span in spans],
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
    }
    asset = _base_asset(
        "professional_book_extraction_run",
        asset_id=extraction_run["extraction_run_id"],
        title="Professional book batch extraction",
        source=project_id,
        tags=["mkaos", "professional-book", "batch-extraction"],
        content=extraction_run,
        metadata={"project_id": project_id, "mkaos": True, "use_in_generation_rag": False},
        references=_dedupe([str(row.get("id") or "") for row in selected_chunks]),
    )
    path = storage.write_asset("runs", asset)
    extraction_run["path"] = _display_path(storage.root, path)
    extraction_run["asset_id"] = asset.id
    return {"extraction_run": extraction_run, "knowledge_candidates": candidates}


def _professional_book_extraction_goal(chunk_content: dict[str, Any]) -> str:
    section = str(chunk_content.get("section_title") or chunk_content.get("chapter_title") or "专业知识")
    text = str(chunk_content.get("clean_text") or "")
    if any(term in text for term in ["证据", "推理", "因果", "线索"]):
        return f"{section} -> 逻辑证据链知识"
    if any(term in text for term in ["制度", "权力", "资源", "组织"]):
        return f"{section} -> 制度冲突机制"
    if any(term in text for term in ["心理", "动机", "选择", "行为"]):
        return f"{section} -> 人物动机机制"
    return f"{section} -> 可迁移专业知识"


def _professional_book_disciplines(chunk_content: dict[str, Any]) -> list[str]:
    text = str(chunk_content.get("clean_text") or "")
    disciplines: list[str] = []
    if any(term in text for term in ["制度", "权力", "资源", "组织"]):
        disciplines.append("制度学")
    if any(term in text for term in ["证据", "推理", "因果", "线索"]):
        disciplines.append("逻辑学")
    if any(term in text for term in ["心理", "动机", "选择", "行为"]):
        disciplines.append("心理学")
    return disciplines or ["专业知识"]


def _generate_professional_book_rule_candidates(storage: LocalStorage, project_id: str, knowledge_candidates: list[dict[str, Any]], payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in knowledge_candidates[: int(payload.get("max_rule_candidates", 8) or 8)]:
        content = item.get("asset", {}).get("content", {}) if isinstance(item.get("asset"), dict) else {}
        concept = str(content.get("concept_name") or "专业知识")
        rule_payload = {
            "project_id": project_id,
            "rule_name": f"{concept} 应用边界检查",
            "rule_type": "professional_book_application",
            "trigger_condition": f"{concept} 被用于小说生产",
            "check_items": ["必须转成人物行动或冲突", "不得出现来源原文表达", "必须保留 evidence span id"],
            "severity": "high",
            "blocking": False,
            "fix_suggestion": "把专业知识转为选择、代价、阻碍、线索或审稿检查。",
            "applicable_flows": ["outline", "chapter_outline", "prose", "review"],
        }
        candidates.append(_persist_rule_card_candidate(storage, project_id, {"knowledge_id": content.get("candidate_id", ""), "concept_name": concept, "tags": ["professional_book"], "severity": "high"}, rule_payload))
    return candidates


def _generate_professional_book_template_candidates(storage: LocalStorage, project_id: str, knowledge_candidates: list[dict[str, Any]], payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in knowledge_candidates[: int(payload.get("max_template_candidates", 8) or 8)]:
        content = item.get("asset", {}).get("content", {}) if isinstance(item.get("asset"), dict) else {}
        template_item = {
            "knowledge_id": str(content.get("candidate_id") or ""),
            "concept_name": str(content.get("concept_name") or "专业知识"),
            "flow": "chapter_outline",
            "platform": str(payload.get("platform") or ""),
            "genre": str(payload.get("genre") or ""),
            "source": "professional_book_import",
            "template_structure": {"beats": ["professional mechanism", "character pressure", "choice cost", "scene proof", "review check"]},
        }
        candidates.append(_persist_template_card_candidate(storage, project_id, template_item, "chapter_outline"))
    return candidates


def _create_professional_book_approval_queue(
    storage: LocalStorage,
    project_id: str,
    knowledge_candidates: list[dict[str, Any]],
    rule_candidates: list[dict[str, Any]],
    template_candidates: list[dict[str, Any]],
    payload: dict[str, Any],
) -> dict[str, Any]:
    approvals: list[dict[str, Any]] = []
    for item in knowledge_candidates[: int(payload.get("max_approval_items", 20) or 20)]:
        asset = item.get("asset", {}) if isinstance(item.get("asset"), dict) else {}
        approval = create_governance_approval(
            storage,
            {
                **payload,
                "project_id": project_id,
                "approval_type": "approve_knowledge_candidate",
                "action_type": "approve_knowledge_candidate",
                "risk_level": "medium",
                "reason": f"Review professional book knowledge candidate: {asset.get('title') or asset.get('id')}",
                "action_payload": {"candidate_id": asset.get("id", ""), "candidate_type": "knowledge_card_candidate"},
                "references": [str(asset.get("id") or "")],
            },
        )
        approvals.append({"approval_id": approval["asset"]["id"], "action_type": "approve_knowledge_candidate", "status": "pending", "path": approval["path"]})
    for candidate in [*rule_candidates, *template_candidates]:
        action_type = "activate_rule" if candidate.get("rule_payload") else "activate_template"
        approval = create_governance_approval(
            storage,
            {
                **payload,
                "project_id": project_id,
                "approval_type": action_type,
                "action_type": action_type,
                "risk_level": "medium",
                "reason": f"Review professional book {action_type}: {candidate.get('rule_name') or candidate.get('template_name') or candidate.get('candidate_id')}",
                "action_payload": {"candidate_id": candidate.get("candidate_id", ""), "rule_payload": candidate.get("rule_payload", {}), "template_payload": candidate.get("template_payload", {})},
                "references": [str(candidate.get("candidate_id") or "")],
            },
        )
        approvals.append({"approval_id": approval["asset"]["id"], "action_type": action_type, "status": "pending", "path": approval["path"]})
    return {"queue_id": _stable_asset_id("professional_book_approval_queue", project_id, str(len(approvals))), "status": "pending", "approval_count": len(approvals), "approvals": approvals}


def _auto_link_professional_book_relations(
    storage: LocalStorage,
    project_id: str,
    knowledge_candidates: list[dict[str, Any]],
    rule_candidates: list[dict[str, Any]],
    template_candidates: list[dict[str, Any]],
    payload: dict[str, Any],
) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    candidate_ids = [str(item.get("asset", {}).get("id") or "") for item in knowledge_candidates if isinstance(item.get("asset"), dict)]
    for left, right in zip(candidate_ids, candidate_ids[1:]):
        if left and right:
            created.append(_create_professional_book_candidate_relation(storage, project_id, left, right, "supports", [left, right], confidence=0.62))
    for rule in rule_candidates:
        kid = str(rule.get("candidate_id") or "")
        if kid and candidate_ids:
            created.append(_create_professional_book_candidate_relation(storage, project_id, candidate_ids[0], kid, "validated_by_rule", [kid], confidence=0.58))
    for template in template_candidates:
        kid = str(template.get("candidate_id") or "")
        if kid and candidate_ids:
            created.append(_create_professional_book_candidate_relation(storage, project_id, candidate_ids[0], kid, "used_by_template", [kid], confidence=0.58))
    return {"relation_count": len(created), "relation_ids": [str(item.get("asset", {}).get("id") or "") for item in created], "source_isolation": {"raw_text_included": False, "clean_text_included": False}}


def _create_professional_book_candidate_relation(storage: LocalStorage, project_id: str, source_id: str, target_id: str, relation_type: str, evidence_refs: list[str], *, confidence: float) -> dict[str, Any]:
    relation_id = _stable_asset_id("knowledge_relation", "professional_book_candidate", source_id, relation_type, target_id)
    content = {
        "relation_id": relation_id,
        "source_knowledge_id": source_id,
        "target_knowledge_id": target_id,
        "relation_type": relation_type,
        "strength": 0.55,
        "confidence": _clamp01(confidence),
        "evidence_refs": _dedupe(evidence_refs),
        "explanation": "Auto-linked during professional book import; relation must be reviewed before production activation.",
        "candidate_relation": True,
        "created_at": utc_now(),
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
    }
    asset = _base_asset(
        "knowledge_relation",
        asset_id=relation_id,
        title=f"{relation_type}: {source_id} -> {target_id}",
        source=source_id,
        tags=["mkaos", "knowledge-relation", "professional-book-candidate", relation_type],
        content=content,
        metadata={"project_id": project_id, "mkaos": True, "use_in_generation_rag": False, "candidate_relation": True},
        references=_dedupe([source_id, target_id, *evidence_refs]),
    )
    path = storage.write_asset("knowledge", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _duplicate_chunk_count(storage: LocalStorage, chunks: list[str]) -> int:
    existing_hashes = {str(row.get("content", {}).get("content_hash") or "") for row in _list_assets(storage, "raw", "source_chunk", limit=5000)}
    return len([chunk for chunk in chunks if _hash_text(chunk) in existing_hashes])


def _abstract_chunk_to_principle(text: str) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if any(term in compact for term in ["土地", "税", "豪强", "制度"]):
        return "制度性资源变化应被抽象为利益分配、行动压力和人物选择代价。"
    if any(term in compact for term in ["线索", "证据", "推理", "谜"]):
        return "悬疑信息应被抽象为公平线索、误导和可复盘证据链。"
    if any(term in compact for term in ["人物", "动机", "关系", "情绪"]):
        return "人物知识应被抽象为目标、动机压力、关系债务和行为约束。"
    return "来源内容应先抽象为可迁移机制，再进入故事目标、冲突、场景或审稿规则。"


def _feedback_issue_tags(text: str) -> list[str]:
    mapping = [
        ("设定太多", "worldbuilding_overload"),
        ("节奏慢", "pacing"),
        ("拖", "pacing"),
        ("人物降智", "character_consistency"),
        ("看不懂", "causal_chain"),
        ("爽点不足", "payoff_density"),
        ("像 AI", "ai_style"),
        ("模板", "template_overuse"),
        ("线索", "mystery_clue"),
        ("反转", "reversal"),
    ]
    tags = [tag for key, tag in mapping if key.lower() in text.lower()]
    return _dedupe(tags)


def _feedback_recommendation(tags: list[str]) -> str:
    if "source_leakage" in tags:
        return "quarantine"
    if {"worldbuilding_overload", "pacing", "template_overuse", "ai_style"} & set(tags):
        return "reduce"
    if {"payoff_density", "mystery_clue", "reversal"} & set(tags):
        return "boost_matching_rules"
    if "character_consistency" in tags:
        return "review"
    return "observe"


def _feedback_sentiment(text: str) -> str:
    negative_terms = ["慢", "拖", "看不懂", "降智", "太多", "像 ai", "无聊", "弃"]
    positive_terms = ["好看", "期待", "爽", "喜欢", "想看"]
    lower = text.lower()
    if any(term in lower for term in negative_terms):
        return "negative"
    if any(term in lower for term in positive_terms):
        return "positive"
    return "neutral"


def _rank_feedback_candidates(storage: LocalStorage, candidate_ids: list[str], tags: list[str]) -> list[dict[str, Any]]:
    ranked = []
    for knowledge_id in candidate_ids:
        try:
            _, knowledge = _find_asset(storage, knowledge_id, asset_type="knowledge_card", categories=["knowledge"])
        except FileNotFoundError:
            continue
        content = knowledge.get("content", {}) if isinstance(knowledge.get("content", {}), dict) else {}
        haystack = json.dumps({"title": knowledge.get("title", ""), "content": content, "tags": knowledge.get("tags", [])}, ensure_ascii=False).lower()
        score = 0.2
        for tag in tags:
            if tag.lower() in haystack:
                score += 0.25
        if not tags:
            score = 0.0
        if score > 0:
            ranked.append({"knowledge_id": knowledge_id, "concept_name": content.get("concept_name", knowledge.get("title", "")), "attribution_score": _clamp01(score), "matched_tags": tags})
    ranked.sort(key=lambda item: (-item["attribution_score"], item["knowledge_id"]))
    return ranked


def _mkaos_issue_type(issue: dict[str, Any]) -> str:
    text = " ".join(str(issue.get(key) or "") for key in ["issue_type", "rule_id", "rule_name", "message", "conflict_type"]).lower()
    if "source" in text or "raw_text" in text:
        return "source_leakage"
    if "canon" in text:
        return "canon_conflict"
    if "platform" in text:
        return "platform_policy_risk"
    if "budget" in text:
        return "context_budget_overflow"
    if "logic" in text or "因果" in text:
        return "plot_logic_gap"
    if "百科" in text or "knowledge" in text or "mkaos" in text:
        return "mkaos_conflict"
    return "mkaos_conflict"


def _revision_instruction_for_issue(issue_type: str) -> str:
    return {
        "source_leakage": "删除疑似原文表达，仅保留抽象机制，并用项目内动作、物件或冲突重写。",
        "canon_conflict": "保持 Canon fact，不得改写角色状态；先建立 canon change 或回滚冲突内容。",
        "platform_policy_risk": "调整章节节奏、钩子和信息密度，不改变主线事实。",
        "ai_style": "把知识解释改写为人物行动、利益冲突和场景变化。",
        "mkaos_conflict": "替换或重排冲突知识，保留可用抽象原则并重新审稿。",
    }.get(issue_type, "按 ReviewIssue 修订，并复核 MKAOS source isolation。")


def _revision_forbidden_changes(issue_type: str) -> list[str]:
    base = ["do not introduce raw source expression", "do not bypass ReviewIssue gate"]
    if issue_type == "canon_conflict":
        base.append("do not silently change canon fact")
    if issue_type == "source_leakage":
        base.append("do not keep suspicious source phrasing")
    return base


def _lineage_report(storage: LocalStorage, *, project_id: str, knowledge_id: str = "", source_document_id: str = "", review_issue_id: str = "") -> dict[str, Any]:
    knowledge_rows = list_knowledge_cards(storage, project_id=project_id if project_id != "local-system" else None, include_deprecated=True, limit=1000)
    if source_document_id:
        chunk_ids = {row["id"] for row in list_source_chunks(storage, source_document_id, limit=1000)}
        knowledge_rows = [row for row in knowledge_rows if chunk_ids & set(_strings(row.get("content", {}).get("source_chunk_ids")))]
    if knowledge_id:
        knowledge_rows = [row for row in knowledge_rows if str(row.get("id") or "") == knowledge_id]
    knowledge_ids = {str(row.get("id") or "") for row in knowledge_rows}
    bindings = [row for row in list_usage_bindings(storage, limit=2000) if str(row.get("content", {}).get("knowledge_id") or "") in knowledge_ids]
    packs = [
        row
        for row in _list_assets(storage, "contexts", "knowledge_pack", project_id=project_id if project_id != "local-system" else None, limit=2000)
        if knowledge_ids & {str(item.get("knowledge_id") or "") for item in row.get("content", {}).get("pack_items", []) if isinstance(item, dict)}
    ]
    context_bundles = [
        row
        for row in _list_assets(storage, "contexts", "context_bundle", project_id=project_id if project_id != "local-system" else None, limit=2000)
        if any(str(row.get("content", {}).get("knowledge_pack", {}).get("knowledge_pack_id", "")) == str(pack.get("id") or "") for pack in packs)
        or str(row.get("content", {}).get("knowledge_context_contract", {}).get("knowledge_pack_id", "")) in {str(pack.get("id") or "") for pack in packs}
    ]
    usage = [row for row in list_usage_events(storage, project_id=project_id if project_id != "local-system" else None, limit=3000) if str(row.get("content", {}).get("knowledge_id") or "") in knowledge_ids]
    review_issues = [
        row
        for row in _list_assets(storage, "reviews", "review_issue", project_id=project_id if project_id != "local-system" else None, limit=2000)
        if knowledge_ids & set(_strings(row.get("content", {}).get("metadata", {}).get("related_knowledge_ids") if isinstance(row.get("content", {}).get("metadata"), dict) else row.get("content", {}).get("evidence_refs")))
        or (review_issue_id and str(row.get("id") or "") == review_issue_id)
    ]
    feedback = [
        row
        for row in _list_assets(storage, "feedback", "knowledge_feedback_attribution", project_id=project_id if project_id != "local-system" else None, limit=1000)
        if knowledge_ids & set(_strings(row.get("content", {}).get("candidate_knowledge_ids")))
    ]
    mutations = [row for row in list_mkaos_mutations(storage, limit=3000) if str(row.get("content", {}).get("asset_id") or "") in knowledge_ids]
    broken = []
    if knowledge_id and not knowledge_rows:
        broken.append("orphan knowledge reference")
    for binding in bindings:
        if str(binding.get("content", {}).get("knowledge_id") or "") not in knowledge_ids:
            broken.append(f"broken binding {binding.get('id')}")
    references = _dedupe(
        [row.get("id", "") for row in knowledge_rows]
        + [row.get("id", "") for row in bindings]
        + [row.get("id", "") for row in packs]
        + [row.get("id", "") for row in context_bundles]
        + [row.get("id", "") for row in review_issues]
        + [row.get("id", "") for row in feedback]
    )
    return {
        "lineage_report_id": _stable_asset_id("knowledge_lineage_report", project_id, knowledge_id, source_document_id, review_issue_id, utc_now()),
        "project_id": project_id,
        "source_document_id": source_document_id,
        "knowledge_ids": sorted(knowledge_ids),
        "knowledge": knowledge_rows,
        "usage_bindings": bindings,
        "knowledge_packs": packs,
        "context_bundles": context_bundles,
        "usage_events": usage,
        "review_issues": review_issues,
        "feedback_attributions": feedback,
        "mutation_audits": mutations,
        "consistency_checks": {"issues": broken, "ok": not broken},
        "references": references,
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
    }


def analyze_knowledge_impact(storage: LocalStorage, knowledge_id: str, *, change_type: str = "update", dry_run: bool = True) -> dict[str, Any]:
    project_id = "local-system"
    try:
        _, knowledge = _find_asset(storage, knowledge_id, asset_type="knowledge_card", categories=["knowledge"])
        project_id = str(knowledge.get("metadata", {}).get("project_id") or "local-system")
    except FileNotFoundError:
        knowledge = {}
    lineage = _lineage_report(storage, project_id=project_id, knowledge_id=knowledge_id)
    content = {
        "impact_report_id": _stable_asset_id("knowledge_impact_report", knowledge_id, change_type, utc_now()),
        "knowledge_id": knowledge_id,
        "change_type": change_type,
        "dry_run": dry_run,
        "affected_packs": [row.get("id", "") for row in lineage["knowledge_packs"]],
        "affected_context_bundles": [row.get("id", "") for row in lineage["context_bundles"]],
        "affected_agent_runs": [row.get("content", {}).get("agent_run_id", "") for row in lineage["usage_events"]],
        "affected_artifacts": [row.get("content", {}).get("target_artifact_id", "") for row in lineage["usage_events"]],
        "affected_review_issues": [row.get("id", "") for row in lineage["review_issues"]],
        "affected_release_packages": [
            row.get("id", "")
            for row in _list_assets(storage, "publishing", "release_package", project_id=project_id if project_id != "local-system" else None, limit=1000)
            if knowledge_id in json.dumps(row, ensure_ascii=False)
        ],
        "recommended_rebuilds": ["knowledge_pack", "context_bundle"] if lineage["knowledge_packs"] else [],
        "recommended_rechecks": ["review", "publish_gate"] if lineage["review_issues"] or lineage["knowledge_packs"] else [],
        "source_isolation": {"raw_text_included": False, "clean_text_included": False},
    }
    if dry_run:
        return content
    asset = _base_asset("knowledge_impact_report", asset_id=content["impact_report_id"], title=f"Knowledge impact {knowledge_id}", source=knowledge_id, tags=["mkaos", "impact-report", change_type], content=content, metadata={"project_id": project_id, "mkaos": True, "use_in_generation_rag": False}, references=[knowledge_id, *content["affected_packs"], *content["affected_review_issues"]])
    path = storage.write_asset("runs", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path), **content}


def _contains_source_text_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in {"raw_text", "clean_text", "source_text", "content_text"}:
                return True
            if _contains_source_text_key(item):
                return True
    if isinstance(value, list):
        return any(_contains_source_text_key(item) for item in value)
    return False


def _actual_blocking(actual: dict[str, Any]) -> bool:
    if actual.get("blocking_count"):
        return True
    if actual.get("passed") is False and actual.get("blocking"):
        return True
    for key in ["issues", "conflicts"]:
        for item in actual.get(key, []) if isinstance(actual.get(key, []), list) else []:
            if isinstance(item, dict) and item.get("blocking"):
                return True
    return False


def _default_regression_cases() -> list[dict[str, Any]]:
    return [
        {"title": "土地兼并", "case_type": "anti_encyclopedia", "input_payload": {"text": "土地兼并的本质是税源转移。\n\n这种制度导致结构变化。"}, "expected_blocking": False, "tags": ["土地兼并"]},
        {"title": "反百科化正例", "case_type": "anti_encyclopedia", "input_payload": {"text": "他把田契按在案上，县丞的手停住了。"}, "expected_blocking": False},
        {"title": "反百科化反例", "case_type": "anti_encyclopedia", "input_payload": {"text": "所谓制度，本质上是资源分配规则。\n\n因此它会导致社会变化。"}, "expected_blocking": False},
        {"title": "source leakage", "case_type": "source_leakage", "input_payload": {"source_leakage_signal": True}, "expected_blocking": True},
        {"title": "canon conflict", "case_type": "knowledge_conflict", "input_payload": {"canon_conflict_result": {"issues": [{"severity": "critical", "blocking": True, "message": "alive/dead conflict"}]}}, "expected_blocking": True},
        {"title": "platform opening rhythm", "case_type": "knowledge_conflict", "input_payload": {"platform": "publishing", "knowledge_items": [{"knowledge_id": "k", "concept_name": "飞卢强爽点模板", "risk_level": "low"}]}, "expected_blocking": False},
        {"title": "causal chain gap", "case_type": "artifact", "input_payload": {"text": "结果突然成功。"}, "expected_blocking": False},
        {"title": "character motivation gap", "case_type": "artifact", "input_payload": {"text": "人物无缘无故背叛。"}, "expected_blocking": False},
        {"title": "pack budget overflow", "case_type": "knowledge_selector", "input_payload": {"flow": "prose", "task_id": "regression-budget", "environment": "compat", "bypass_reason": "regression"}, "expected_blocking": False},
        {"title": "disabled binding", "case_type": "knowledge_conflict", "input_payload": {"knowledge_items": [{"knowledge_id": "k", "status": "do_not_select"}]}, "expected_blocking": True},
    ]


def _rewrite_suggestion_for_issue(issue: dict[str, Any]) -> str:
    message = str(issue.get("message") or "")
    if "对话" in message:
        return "转成对话冲突"
    if "物件" in message or "场景" in message:
        return "转成场景动作"
    if "解释" in message:
        return "转成人物目标和选择代价"
    return "转成利益冲突"


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return any(str(item_key) == key or _contains_key(item_value, key) for item_key, item_value in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False
