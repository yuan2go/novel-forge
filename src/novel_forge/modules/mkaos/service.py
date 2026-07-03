from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path, run_metadata
from novel_forge.modules.os_envelope import enforce_os_envelope, envelope_asset_metadata, envelope_response
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import (
    KnowledgeCard,
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

MKAOS_FLOWS = {"outline", "chapter_outline", "prose", "review"}
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
    status = str(payload.get("status") or "active").strip()
    risk_level = str(payload.get("risk_level") or "low").strip()
    content = {
        "concept_name": concept_name,
        "concept_aliases": _strings(payload.get("concept_aliases")),
        "discipline": str(payload.get("discipline") or "general").strip(),
        "sub_discipline": str(payload.get("sub_discipline") or "").strip(),
        "knowledge_type": str(payload.get("knowledge_type") or "mechanism").strip(),
        "core_explanation": core,
        "principles": _strings(payload.get("principles")) or [core],
        "source_chunk_ids": source_chunk_ids,
        "confidence": _float(payload.get("confidence"), 0.7),
        "source_reliability": _float(payload.get("source_reliability"), 0.7),
        "applicable_genres": _strings(payload.get("applicable_genres")),
        "applicable_platforms": _strings(payload.get("applicable_platforms")),
        "risk_level": risk_level,
        "risk_notes": str(payload.get("risk_notes") or "").strip(),
        "status": status,
        "quality_score": _float(payload.get("quality_score"), 0.7),
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
            "weight": content["weight"],
            "source_chunk_ids": source_chunk_ids,
            "copyright_boundary": "abstract structure knowledge card derived from source evidence; no raw source expression for prose",
            "run_metadata": run_metadata("mkaos.create_knowledge_card", KnowledgeCard(title=concept_name, content={"principles": [core]})),
            **envelope_asset_metadata(os_envelope),
        },
        references=filter_project_safe_references(storage, project_id, source_chunk_ids),
    )
    _ensure_valid(asset.to_dict())
    path = storage.write_asset("knowledge", asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path), "validation": {"ok": True, "errors": []}}


def update_knowledge_card(storage: LocalStorage, knowledge_ref: str | Path, patch: dict[str, Any]) -> dict[str, Any]:
    path, data = _find_asset(storage, knowledge_ref, asset_type="knowledge_card", categories=["knowledge"])
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    project_id = str(patch.get("project_id") or metadata.get("project_id") or "local-system")
    os_envelope = _mkaos_envelope(storage, patch, operation="mkaos.knowledge_update", asset_type="knowledge_card", project_id=project_id, task_type="knowledge_update")
    for key, value in patch.items():
        if key in {"metadata", "content"}:
            continue
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
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path), "validation": {"ok": True, "errors": []}}


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
    bindings = list_usage_bindings(storage, flow=flow, enabled=True, limit=500)
    knowledge_items: list[dict[str, Any]] = []
    for binding in bindings:
        item = _pack_item_from_binding(storage, binding, flow, genre=genre, platform=platform, project_id=project_id)
        if item:
            knowledge_items.append(item)
    knowledge_items.sort(key=lambda item: (int(item.get("priority", 100)), -float(item.get("weight", 1.0))))
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
    text = str(payload.get("artifact_text") or payload.get("text") or "")
    project_id = str(payload.get("project_id") or "local-system")
    canon = payload.get("canon") if isinstance(payload.get("canon"), dict) else _canon_context(storage, project_id)
    facts = canon.get("facts", []) if isinstance(canon.get("facts", []), list) else []
    facts.extend(canon.get("entities", []) if isinstance(canon.get("entities", []), list) else [])
    claims = payload.get("claims", []) if isinstance(payload.get("claims", []), list) else []
    issues: list[dict[str, Any]] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        entity = str(claim.get("entity") or claim.get("name") or "").strip()
        key = str(claim.get("key") or claim.get("field") or "status").strip()
        value = str(claim.get("value") or "").strip()
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            fact_entity = str(fact.get("entity") or fact.get("name") or fact.get("canonical_name") or "").strip()
            fact_value = str(fact.get(key) or fact.get("status") or fact.get("state") or "").strip()
            if entity and fact_entity and entity == fact_entity and value and fact_value and value != fact_value:
                issues.append(_issue("rule_canon_conflict", "Canon 冲突检查", "critical", True, f"{entity} 的 {key}={value} 与 Canon={fact_value} 冲突。", "创建正典变更任务或回滚冲突产物。", "artifact"))
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        name = str(fact.get("canonical_name") or fact.get("name") or fact.get("entity") or "").strip()
        status = str(fact.get("status") or fact.get("state") or "").strip().lower()
        if not name or not text:
            continue
        if status in {"alive", "存活", "在世"} and name in text and any(term in text for term in ["死了", "死亡", "尸体", "被杀"]):
            issues.append(_issue("rule_canon_conflict", "Canon 冲突检查", "critical", True, f"{name} 被 Canon 标记为存活，但文本出现死亡声明。", "回滚死亡声明或提交正典变更。", "artifact"))
        if status in {"dead", "死亡", "已死"} and name in text and any(term in text for term in ["还活着", "现身", "开口说"]):
            issues.append(_issue("rule_canon_conflict", "Canon 冲突检查", "critical", True, f"{name} 被 Canon 标记为死亡，但文本出现存活行动。", "改为回忆、伪装或提交正典变更。", "artifact"))
    return {"passed": not issues, "issues": issues, "canon_source": canon.get("source", "payload_or_project_stub")}


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
    score = _record_quality_score(
        storage,
        knowledge_id=knowledge_id,
        flow=flow,
        delta=delta,
        reason=str(payload.get("reason") or "weight_update"),
        metadata={"previous_weight": previous_weight, "next_weight": next_weight, "status": status, "payload": payload, **envelope_asset_metadata(os_envelope)},
    )
    return {"knowledge": {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}, "quality_score": score, "delta": delta, "status": status}


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


def _pack_item_from_binding(storage: LocalStorage, binding: dict[str, Any], flow: str, *, genre: str, platform: str, project_id: str = "") -> dict[str, Any] | None:
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
    if _knowledge_status(knowledge) in {"deprecated"}:
        return None
    kcontent = knowledge.get("content", {}) if isinstance(knowledge.get("content", {}), dict) else {}
    if not _genre_matches(kcontent.get("applicable_genres", []), genre):
        return None
    if not _platform_matches(kcontent.get("applicable_platforms", []), platform):
        return None
    role = _pack_role_from_binding(content, flow)
    return {
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
    }


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
    else:
        max_core = 3 if flow == "prose" else 8
    return {
        "max_core_knowledge": max_core,
        "max_items": max(6, max_core * 3),
        "anti_encyclopedia_required": flow == "prose",
        "source_chunk_raw_text_allowed": False,
    }


def _output_contract(flow: str) -> dict[str, Any]:
    contracts = {
        "outline": {"must_include": ["logic_constraints", "review_rule_refs"], "must_not_include": ["draft prose"]},
        "chapter_outline": {"must_include": ["goal", "obstacle", "action", "result", "information_change", "emotion", "hook"]},
        "prose": {"must_include": ["allowed_knowledge_points", "knowledge_budget"], "must_not_include": ["source_chunk.raw_text", "encyclopedia paragraphs"]},
        "review": {"must_include": ["rule_id", "rule_name", "severity", "blocking", "message", "fix_suggestion", "rollback_level"]},
    }
    return contracts[flow]


def _canon_context(storage: LocalStorage, project_id: str) -> dict[str, Any]:
    rows = _list_assets(storage, "continuity", "canon_database", project_id=project_id if project_id != "local-system" else None, limit=20)
    if not rows:
        return {"source": "stub", "facts": [], "entities": [], "rules": [], "warnings": ["canon_database not found; stub used"]}
    facts: list[Any] = []
    entities: list[Any] = []
    rules: list[Any] = []
    refs: list[str] = []
    for row in rows:
        content = row.get("content", {})
        facts.extend(content.get("facts", []) if isinstance(content.get("facts", []), list) else [])
        entities.extend(content.get("entities", []) if isinstance(content.get("entities", []), list) else [])
        rules.extend(content.get("rules", []) if isinstance(content.get("rules", []), list) else [])
        refs.append(row.get("path", ""))
    return {"source": "canon_database", "facts": facts, "entities": entities, "rules": rules, "references": refs}


def _anti_encyclopedia_issues(storage: LocalStorage, text: str) -> list[dict[str, Any]]:
    if not text.strip():
        return []
    rules = ensure_default_rule_cards(storage)
    rule_id = next((row.get("id", "") for row in rules if row.get("content", {}).get("rule_type") == "anti_encyclopedia"), "rule_anti_encyclopedia")
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    explanation_keywords = ["制度", "本质", "所谓", "因此", "导致", "概念", "规则", "税源", "土地兼并", "专业上", "定义"]
    explanatory = [
        index
        for index, paragraph in enumerate(paragraphs)
        if len(paragraph) >= 25 and any(keyword in paragraph for keyword in explanation_keywords) and not _has_scene_or_dialogue(paragraph)
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
        raise ValueError("flow must be outline, chapter_outline, prose, or review")
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
    return {"outline": "required", "chapter_outline": "required", "prose": "optional", "review": "review_rule"}[flow]


def _default_input_role(flow: str) -> str:
    return {"outline": "required", "chapter_outline": "required", "prose": "optional", "review": "review_rule"}[flow]


def _default_output_form(flow: str) -> str:
    return {
        "outline": "logic constraint",
        "chapter_outline": "scene conflict",
        "prose": "action/dialogue/object/scene",
        "review": "review issue contract",
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


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return any(str(item_key) == key or _contains_key(item_value, key) for item_key, item_value in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False
