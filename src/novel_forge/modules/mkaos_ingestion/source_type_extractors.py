from __future__ import annotations

import hashlib
import re
from typing import Any

from .source_type_registry import source_type_profile


def classical_text_extractor(payload: dict[str, Any]) -> list[dict[str, Any]]:
    text = _input_text(payload)
    theme = _concept_from_text(text, "秩序机制")
    return [_creative_card_payload(payload, concept_name=theme, source_type="classical_text", discipline="classical_literature", knowledge_type="world_rule", creative_principle="将礼法、伦理或宗族秩序抽象成约束人物选择的制度压力。", narrative_function="制造个人目标与秩序义务之间的冲突。", conflict_function="让资源、名分、继承或声望发生可见得失。", character_function="适合克制型主角、伪善长辈、破局谋士和被秩序牺牲的人物。", worldbuilding_function="沉淀为礼法、宗族、官府或门阀的世界规则。")]


def webnovel_extractor(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [_creative_card_payload(payload, concept_name=_concept_from_text(_input_text(payload), "章节爽点机制"), source_type="webnovel_analysis", discipline="commercial_narrative", knowledge_type="chapter_hook", creative_principle="把信息差、身份差和即时回报转成章节钩子与付费点。", narrative_function="提高章节推进速度和下一章期待。", conflict_function="让主角在短时间内面对明确阻碍并获得可感知收益。", character_function="强化主角目标、身份反差和对手压迫。", worldbuilding_function="只保留服务爽点和冲突的设定。")]


def professional_book_extractor(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [_creative_card_payload(payload, concept_name=_concept_from_text(_input_text(payload), "专业机制"), source_type="professional_book", discipline="professional_knowledge", knowledge_type="review_rule", creative_principle="把专业概念抽象为可迁移的方法、约束和因果机制。", narrative_function="让专业知识影响行动选择、资源配置和风险后果。", conflict_function="将理论差异转成利益冲突或方法冲突。", character_function="揭示角色专业能力、判断偏差和选择代价。", worldbuilding_function="定义行业、制度或技术运行边界。")]


def mystery_extractor(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [_creative_card_payload(payload, concept_name=_concept_from_text(_input_text(payload), "证据链机制"), source_type="mystery", discipline="logic", knowledge_type="conflict_pattern", creative_principle="把事实、误导和读者认知差组织成公平线索链。", narrative_function="控制读者问题、怀疑对象和反转时机。", conflict_function="让证据的解释权成为人物之间的攻防。", character_function="通过动机、机会和行为偏差呈现人物秘密。", worldbuilding_function="让场景规则成为线索成立或失效的边界。")]


def extract_by_source_type(source_type: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    if source_type == "classical_text":
        return classical_text_extractor(payload)
    if source_type == "webnovel_analysis":
        return webnovel_extractor(payload)
    if source_type == "mystery":
        return mystery_extractor(payload)
    return professional_book_extractor(payload)


def _creative_card_payload(payload: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    source_type = str(overrides.get("source_type") or payload.get("source_type") or "professional_book")
    profile = source_type_profile(source_type)
    concept_name = str(overrides.get("concept_name") or "Creative mechanism").strip()
    evidence_refs = [str(item) for item in payload.get("evidence_refs") or payload.get("source_chunk_ids") or [] if str(item).strip()]
    core_explanation = str(payload.get("core_explanation") or overrides.get("creative_principle") or "abstract reusable creative mechanism").strip()
    applicable_flows = list(dict.fromkeys([*profile.get("recommended_flows", []), *[str(item) for item in payload.get("applicable_flows") or []]]))
    return {
        "knowledge_subtype": "creative_knowledge_card",
        "concept_name": concept_name,
        "source_type": source_type,
        "discipline": str(overrides.get("discipline") or (profile.get("default_disciplines") or ["general"])[0]),
        "knowledge_type": str(overrides.get("knowledge_type") or "mechanism"),
        "abstraction_level": str(payload.get("abstraction_level") or "mechanism"),
        "core_explanation": core_explanation,
        "creative_principle": str(overrides.get("creative_principle") or core_explanation),
        "narrative_function": str(overrides.get("narrative_function") or "turn knowledge into narrative pressure"),
        "conflict_function": str(overrides.get("conflict_function") or "create visible conflict and stakes"),
        "character_function": str(overrides.get("character_function") or "shape motivation, bias, or choice cost"),
        "worldbuilding_function": str(overrides.get("worldbuilding_function") or "define reusable world constraint"),
        "prose_function": str(payload.get("prose_function") or "present through action, dialogue, object, or scene pressure"),
        "review_function": str(payload.get("review_function") or "check that knowledge changes action, conflict, or consequence"),
        "positive_usage": payload.get("positive_usage") or ["turn abstract concept into conflict, choice, and cost"],
        "negative_usage": payload.get("negative_usage") or ["do not explain as an encyclopedia paragraph", "do not copy source expression"],
        "anti_patterns": payload.get("anti_patterns") or ["百科化", "原文复用", "概念堆叠"],
        "applicable_flows": applicable_flows,
        "originality_boundary": str(payload.get("originality_boundary") or "Use abstract mechanism only; do not reuse source wording, characters, scenes, or source-specific sequence."),
        "source_chunk_ids": evidence_refs,
        "evidence_span_refs": [str(item) for item in payload.get("evidence_span_refs") or [] if str(item).strip()],
        "quality_dimensions": {
            "abstraction_score": 0.78,
            "creative_usability_score": 0.78,
            "flow_binding_score": 0.8 if applicable_flows else 0.2,
            "anti_exposition_score": 0.78,
            "originality_safety_score": 0.82,
        },
        "metadata": {
            "extractor": str(payload.get("extractor") or profile.get("extractor") or "deterministic_first_slice"),
            "input_hash": hashlib.sha256(_input_text(payload).encode("utf-8")).hexdigest(),
            "provider_mode": "deterministic_local",
        },
    }


def _input_text(payload: dict[str, Any]) -> str:
    return str(payload.get("text") or payload.get("clean_text") or payload.get("summary") or payload.get("content") or "")


def _concept_from_text(text: str, fallback: str) -> str:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return fallback
    return f"{compact[:12]}{fallback}" if len(compact) > 4 else fallback
