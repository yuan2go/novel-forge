from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, slugify, utc_now
from novel_forge.modules.common import run_metadata
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.schemas import (
    PlatformChapterGate,
    PlatformFeedbackBackflow,
    PlatformOpeningGate,
    PlatformProfile,
    PlatformPublishAdapter,
    PlatformRetentionRisk,
    PlatformRhythmRule,
    PlatformStrategyPack,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage

PLATFORM_ASSET_TYPES = {
    "platform_profile",
    "platform_rhythm_rule",
    "platform_opening_gate",
    "platform_chapter_gate",
    "platform_retention_risk",
    "platform_publish_adapter",
    "platform_feedback_backflow",
    "platform_strategy_pack",
}

PLATFORM_ALIASES = {
    "起点": "qidian",
    "起点中文网": "qidian",
    "qidian": "qidian",
    "番茄": "fanqie",
    "番茄小说": "fanqie",
    "fanqie": "fanqie",
    "飞卢": "feilu",
    "飞卢小说": "feilu",
    "feilu": "feilu",
    "晋江": "jinjiang",
    "晋江文学城": "jinjiang",
    "jinjiang": "jinjiang",
    "知乎": "zhihu_yanxuan",
    "知乎盐选": "zhihu_yanxuan",
    "zhihu": "zhihu_yanxuan",
    "zhihu_yanxuan": "zhihu_yanxuan",
    "微信读书": "wechat_publish",
    "出版": "wechat_publish",
    "出版向": "wechat_publish",
    "微信读书/出版向": "wechat_publish",
    "wechat_reading": "wechat_publish",
    "wechat_publish": "wechat_publish",
}

DEFAULT_PLATFORM_STRATEGIES: dict[str, dict[str, Any]] = {
    "qidian": {
        "platform_name": "起点",
        "business_model": "paid_serial",
        "chapter_length_range": {"min": 2500, "ideal": 3200, "max": 4200},
        "reader_expectation": ["长线成长", "世界观厚度", "稳定主线", "付费节点前连续钩子"],
        "review_risks": ["主线断裂", "设定兑现不足", "成长线停滞", "付费前缺少留存承诺"],
        "genre_fit": ["玄幻", "仙侠", "都市", "历史", "科幻", "长篇群像"],
        "style_tendency": ["清晰设定", "升级反馈", "长线伏笔", "章节目标明确"],
        "strategy_axes": ["long_growth", "world_depth", "paid_retention", "mainline_stability"],
        "beat_cadence": ["世界规则压力", "成长选择", "资源或身份收益", "更大主线义务"],
        "opening_signals": ["主线危机", "成长承诺", "世界规则可见", "长期问题"],
        "chapter_beats": ["目标推进", "规则应用", "成长收益", "章节末主线钩子"],
        "payoff_cadence": "每 2-3 章兑现小收益，每 8-12 章兑现阶段收益",
        "hook_policy": "章节结尾必须改变下一章目标或升级主线风险",
        "paywall_policy": "付费节点前连续建立目标、收益和未解主线问题",
        "retention_focus": ["主线稳定", "升级反馈", "付费前承诺"],
        "publish_checklist": ["章节标题体现目标", "摘要包含主线推进", "付费节点前不弱化爽点"],
    },
    "fanqie": {
        "platform_name": "番茄",
        "business_model": "free_ad",
        "chapter_length_range": {"min": 1600, "ideal": 2200, "max": 2800},
        "reader_expectation": ["快节奏", "强情绪", "强反转", "低阅读门槛"],
        "review_risks": ["开局慢", "信息密度过高", "情绪不够直接", "反转间隔过长"],
        "genre_fit": ["都市", "现言", "脑洞", "悬疑", "短平快爽文"],
        "style_tendency": ["短句", "情绪直给", "低门槛设定", "高频反转"],
        "strategy_axes": ["fast_pace", "strong_emotion", "reversal_density", "low_barrier"],
        "beat_cadence": ["直接压力", "强情绪选择", "反转", "即时反馈"],
        "opening_signals": ["三段内冲突", "强情绪痛点", "低门槛问题", "首章反转"],
        "chapter_beats": ["开场压力", "情绪抬升", "反转或误会", "即时爽点", "短钩子"],
        "payoff_cadence": "每章至少一个情绪回报或反转",
        "hook_policy": "开头 300 字进入冲突，结尾留下强情绪悬念",
        "paywall_policy": "免费阅读也要保持单章强反馈和低理解成本",
        "retention_focus": ["开局速度", "情绪反馈", "反转密度"],
        "publish_checklist": ["标题有情绪或反差", "摘要能一眼读懂", "章节不堆设定"],
    },
    "feilu": {
        "platform_name": "飞卢",
        "business_model": "paid_serial",
        "chapter_length_range": {"min": 1800, "ideal": 2300, "max": 3000},
        "reader_expectation": ["高密度爽点", "强设定", "强身份差", "快速反馈"],
        "review_risks": ["爽点不足", "身份差不明显", "设定反馈慢", "章节目标不够锋利"],
        "genre_fit": ["同人", "系统", "历史脑洞", "都市脑洞", "轻设定爽文"],
        "style_tendency": ["设定强展示", "身份差拉满", "短周期奖励", "反馈明确"],
        "strategy_axes": ["pleasure_density", "strong_premise", "identity_gap", "fast_feedback"],
        "beat_cadence": ["身份差展示", "规则压制", "反手收益", "围观反馈"],
        "opening_signals": ["强设定一句话成立", "身份差可见", "首章爽点", "快速奖励"],
        "chapter_beats": ["身份差", "压制或挑衅", "反手打脸", "奖励反馈", "下一次更大挑衅"],
        "payoff_cadence": "每章至少一个明确爽点，每 3 章有设定升级",
        "hook_policy": "结尾给下一次更高身份差或更大奖励预期",
        "paywall_policy": "付费前展示设定可持续产出爽点",
        "retention_focus": ["爽点密度", "设定收益", "身份差升级"],
        "publish_checklist": ["标题突出设定和身份差", "摘要突出爽点", "避免慢热铺垫"],
    },
    "jinjiang": {
        "platform_name": "晋江",
        "business_model": "paid_serial",
        "chapter_length_range": {"min": 2200, "ideal": 3000, "max": 4200},
        "reader_expectation": ["人物关系", "情绪张力", "人设吸引力", "关系推进"],
        "review_risks": ["人设功能弱", "关系张力不足", "情绪转折无铺垫", "角色魅力不清"],
        "genre_fit": ["言情", "纯爱", "女性向幻想", "关系驱动悬疑"],
        "style_tendency": ["人物动机清楚", "关系张力", "情绪细节", "人设记忆点"],
        "strategy_axes": ["relationship_tension", "emotional_arc", "character_charm", "bond_progression"],
        "beat_cadence": ["关系压力", "误解或吸引", "情绪选择", "关系状态变化"],
        "opening_signals": ["角色魅力点", "关系张力", "情绪缺口", "互动钩子"],
        "chapter_beats": ["人物欲望", "关系摩擦", "情绪抉择", "关系微变", "互动悬念"],
        "payoff_cadence": "每章推进关系认知或情绪状态，每卷兑现关系阶段变化",
        "hook_policy": "结尾让关系状态、误会或情绪选择发生变化",
        "paywall_policy": "付费前明确人物吸引力和关系张力的可持续性",
        "retention_focus": ["关系张力", "人设魅力", "情绪兑现"],
        "publish_checklist": ["标题或摘要突出人设/关系", "章节尾有互动期待", "避免纯事件推进"],
    },
    "zhihu_yanxuan": {
        "platform_name": "知乎盐选",
        "business_model": "paid_serial",
        "chapter_length_range": {"min": 1800, "ideal": 2600, "max": 3600},
        "reader_expectation": ["强钩子", "现实感", "短中篇结构", "反转密度"],
        "review_risks": ["开篇问题不尖锐", "现实逻辑弱", "反转无证据", "篇幅失控"],
        "genre_fit": ["现实悬疑", "情感反转", "职场", "家庭", "社会议题"],
        "style_tendency": ["第一人称冲击", "现实细节", "证据链", "短中篇收束"],
        "strategy_axes": ["sharp_hook", "realism", "short_mid_structure", "reversal_density"],
        "beat_cadence": ["现实异常", "证据推进", "认知反转", "新问题"],
        "opening_signals": ["首段问题", "现实细节", "冲突对象", "反常证据"],
        "chapter_beats": ["现实问题", "证据", "反转", "代价", "更深问题"],
        "payoff_cadence": "每章推进证据或反转，短中篇避免长线拖延",
        "hook_policy": "开头首段必须有问题，结尾给认知反转或证据缺口",
        "paywall_policy": "付费节点前让读者相信后续有答案和更大反转",
        "retention_focus": ["首段钩子", "现实可信", "反转证据"],
        "publish_checklist": ["标题像真实问题", "摘要突出反常事实", "章节控制反转密度"],
    },
    "wechat_publish": {
        "platform_name": "微信读书/出版向",
        "business_model": "ip_publish",
        "chapter_length_range": {"min": 2500, "ideal": 3800, "max": 5200},
        "reader_expectation": ["文学质感", "结构完整", "主题表达", "语言稳定"],
        "review_risks": ["主题散乱", "结构松散", "语言漂移", "商业钩子破坏质感"],
        "genre_fit": ["出版向悬疑", "现实题材", "文学类型融合", "精品长篇"],
        "style_tendency": ["语言稳定", "结构闭合", "主题线索", "人物复杂度"],
        "strategy_axes": ["literary_quality", "structural_integrity", "theme_expression", "language_stability"],
        "beat_cadence": ["主题意象", "人物选择", "结构推进", "余韵"],
        "opening_signals": ["主题意象", "人物困境", "语言稳定", "结构承诺"],
        "chapter_beats": ["主题触点", "人物细节", "结构推进", "情绪余韵", "克制钩子"],
        "payoff_cadence": "每章保留结构推进和主题回声，不牺牲语言稳定",
        "hook_policy": "钩子服务结构和主题，不使用破坏质感的强行悬念",
        "paywall_policy": "以完整结构、人物深度和语言信任驱动阅读",
        "retention_focus": ["语言稳定", "结构完整", "主题辨识度"],
        "publish_checklist": ["标题克制准确", "摘要突出主题和结构", "发布包包含编辑说明"],
    },
}


def ensure_default_platform_strategy_assets(storage: LocalStorage) -> dict[str, Any]:
    storage.ensure_layout()
    existing = _assets_by_type(storage, "platforms", PLATFORM_ASSET_TYPES)
    existing_keys = {
        (row["type"], str(row["content"].get("platform_id") or row["content"].get("rule_id") or row["content"].get("gate_id") or row["content"].get("adapter_id") or ""))
        for row in existing
    }
    created: list[dict[str, Any]] = []
    for platform_id, spec in DEFAULT_PLATFORM_STRATEGIES.items():
        assets = [
            _profile_asset(platform_id, spec),
            _rhythm_asset(platform_id, spec),
            _opening_gate_asset(platform_id, spec),
            _chapter_gate_asset(platform_id, spec),
            _publish_adapter_asset(platform_id, spec),
            _feedback_backflow_asset(platform_id, spec, project_id="", signals=[]),
        ]
        for asset in assets:
            content = asset.content if isinstance(asset.content, dict) else {}
            key = str(content.get("platform_id") or content.get("rule_id") or content.get("gate_id") or content.get("adapter_id") or "")
            if (asset.type, key) in existing_keys:
                continue
            created.append(_write(storage, asset))
    return {"created_count": len(created), "created": created, "platform_count": len(DEFAULT_PLATFORM_STRATEGIES)}


def list_platform_strategy_assets(storage: LocalStorage, *, platform: str | None = None, asset_type: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    ensure_default_platform_strategy_assets(storage)
    platform_id = _platform_id(platform or "")
    rows = _assets_by_type(storage, "platforms", PLATFORM_ASSET_TYPES, limit=limit)
    if asset_type:
        rows = [row for row in rows if row["type"] == asset_type]
    if platform_id:
        rows = [row for row in rows if str(row["content"].get("platform_id", "")) == platform_id]
    return rows


def build_platform_strategy_pack(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_default_platform_strategy_assets(storage)
    platform_id = _platform_id(str(payload.get("platform") or payload.get("platform_id") or payload.get("target_platform") or "qidian"))
    spec = DEFAULT_PLATFORM_STRATEGIES.get(platform_id, DEFAULT_PLATFORM_STRATEGIES["qidian"])
    project_id = str(payload.get("project_id") or "local-system")
    workspace_path = str(payload.get("workspace_path") or "")
    topic = str(payload.get("topic") or payload.get("title") or payload.get("project_title") or "Untitled topic")
    genre = str(payload.get("genre") or "generic")
    chapter = payload.get("chapter")
    profile = _find_platform_asset(storage, "platform_profile", platform_id) or _profile_asset(platform_id, spec).to_dict()
    rhythm_rule = _find_platform_asset(storage, "platform_rhythm_rule", platform_id) or _rhythm_asset(platform_id, spec).to_dict()
    opening_gate = _find_platform_asset(storage, "platform_opening_gate", platform_id) or _opening_gate_asset(platform_id, spec).to_dict()
    chapter_gate = _find_platform_asset(storage, "platform_chapter_gate", platform_id) or _chapter_gate_asset(platform_id, spec).to_dict()
    publish_adapter = _find_platform_asset(storage, "platform_publish_adapter", platform_id) or _publish_adapter_asset(platform_id, spec).to_dict()
    feedback_backflow = _find_platform_asset(storage, "platform_feedback_backflow", platform_id) or _feedback_backflow_asset(platform_id, spec, project_id=project_id, signals=[]).to_dict()
    pack_id = str(payload.get("pack_id") or _stable_platform_asset_id("platform_strategy_pack", project_id, platform_id, genre, topic, str(chapter or "project")))
    content = {
        "pack_id": pack_id,
        "project_id": project_id,
        "workspace_path": workspace_path,
        "platform_id": platform_id,
        "platform_name": spec["platform_name"],
        "topic": topic,
        "genre": genre,
        "chapter": chapter,
        "profile": _trim_asset(profile),
        "rhythm_rule": _trim_asset(rhythm_rule),
        "opening_gate": _trim_asset(opening_gate),
        "chapter_gate": _trim_asset(chapter_gate),
        "publish_adapter": _trim_asset(publish_adapter),
        "feedback_backflow": _trim_asset(feedback_backflow),
        "outline_strategy": _outline_strategy(platform_id, spec, topic, genre),
        "chapter_strategy": _chapter_strategy(platform_id, spec),
        "prose_strategy": _prose_strategy(platform_id, spec),
        "validation_policy": _validation_policy(platform_id, spec),
        "strategy_comparison_axis": spec["strategy_axes"],
        "created_at": utc_now(),
    }
    asset = PlatformStrategyPack(
        id=pack_id,
        title=f"{spec['platform_name']} strategy pack: {topic}",
        source=platform_id,
        tags=["platform-strategy", platform_id, genre],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "use_in_generation_rag": False, "run_metadata": run_metadata("platform_strategy.build_pack", PlatformStrategyPack(title="platform strategy", content={"pack_id": pack_id}))},
        references=filter_project_safe_references(storage, project_id, _dedupe([workspace_path, profile.get("id", ""), rhythm_rule.get("id", ""), opening_gate.get("id", ""), chapter_gate.get("id", ""), publish_adapter.get("id", ""), feedback_backflow.get("id", "")])),
    )
    if bool(payload.get("persist", True)):
        result = _write(storage, asset)
        return {"path": result["path"], "asset": result["asset"], "strategy": content}
    _ensure_valid(asset.to_dict())
    return {"path": "", "asset": asset.to_dict(), "strategy": content}


def evaluate_platform_opening_gate(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    pack = build_platform_strategy_pack(storage, {**payload, "persist": bool(payload.get("persist_pack", False))})
    content = pack["asset"]["content"]
    text = _payload_text(payload)
    required = _strings(content.get("opening_gate", {}).get("content", {}).get("required_signals")) or _strings(content.get("opening_gate", {}).get("required_signals"))
    signals = _detected_signals(text, required)
    score = _gate_score(signals, required, text=text, platform_id=content["platform_id"], opening=True)
    threshold = _threshold(content.get("opening_gate", {}), "pass", 70)
    result = {
        "platform_id": content["platform_id"],
        "platform_name": content["platform_name"],
        "passed": score >= threshold,
        "score": score,
        "threshold": threshold,
        "detected_signals": signals,
        "missing_signals": [item for item in required if item not in signals],
        "revision_hints": _strings(content.get("opening_gate", {}).get("content", {}).get("revision_hints")) or _strings(content.get("opening_gate", {}).get("revision_hints")),
        "strategy_pack_path": pack["path"],
    }
    return result


def evaluate_platform_chapter_gate(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    pack = build_platform_strategy_pack(storage, {**payload, "persist": bool(payload.get("persist_pack", False))})
    content = pack["asset"]["content"]
    text = _payload_text(payload)
    required = _strings(content.get("chapter_gate", {}).get("content", {}).get("required_beats")) or _strings(content.get("chapter_gate", {}).get("required_beats"))
    signals = _detected_signals(text, required)
    word_count = len(text)
    word_budget = content.get("chapter_strategy", {}).get("word_budget", {})
    score = _gate_score(signals, required, text=text, platform_id=content["platform_id"], opening=False)
    if isinstance(word_budget, dict) and word_budget.get("min") and word_count < int(word_budget["min"]) * 0.35:
        score = max(0, score - 15)
    threshold = _threshold(content.get("chapter_gate", {}), "pass", 72)
    result = {
        "platform_id": content["platform_id"],
        "platform_name": content["platform_name"],
        "passed": score >= threshold,
        "score": score,
        "threshold": threshold,
        "detected_beats": signals,
        "missing_beats": [item for item in required if item not in signals],
        "word_count": word_count,
        "word_budget": word_budget,
        "ending_hook": content.get("chapter_strategy", {}).get("ending_hook", ""),
        "strategy_pack_path": pack["path"],
    }
    return result


def assess_platform_retention_risk(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    pack = build_platform_strategy_pack(storage, {**payload, "persist": bool(payload.get("persist_pack", False))})
    content = pack["asset"]["content"]
    project_id = str(payload.get("project_id") or content.get("project_id") or "local-system")
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    feedback = payload.get("feedback") if isinstance(payload.get("feedback"), list) else []
    score, signals = _retention_score(content["platform_id"], metrics, feedback)
    level = "critical" if score >= 85 else "high" if score >= 65 else "medium" if score >= 35 else "low"
    risk_id = make_id("platform_retention_risk", f"{project_id}-{content['platform_id']}-{utc_now()}")
    risk_asset = PlatformRetentionRisk(
        id=risk_id,
        title=f"{content['platform_name']} retention risk",
        source=pack["asset"]["id"],
        tags=["platform-retention-risk", content["platform_id"], level],
        content={
            "risk_id": risk_id,
            "platform_id": content["platform_id"],
            "project_id": project_id,
            "risk_level": level,
            "risk_score": score,
            "signals": signals,
            "mitigation_plan": _retention_mitigation(content, signals),
            "evidence_refs": _strings(payload.get("evidence_refs")),
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "workspace_path": content.get("workspace_path", ""), "use_in_generation_rag": False},
        references=filter_project_safe_references(storage, project_id, _dedupe([pack["path"], *_strings(payload.get("evidence_refs"))])),
    )
    return _write(storage, risk_asset)


def prepare_platform_publish_adapter(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    pack = build_platform_strategy_pack(storage, {**payload, "persist": bool(payload.get("persist_pack", True))})
    content = pack["asset"]["content"]
    adapter = content.get("publish_adapter", {}).get("content", content.get("publish_adapter", {}))
    return {
        "platform_id": content["platform_id"],
        "platform_name": content["platform_name"],
        "strategy_pack_path": pack["path"],
        "adapter": adapter,
        "release_payload_contract": {
            "title_strategy": adapter.get("metadata_rules", {}).get("title", ""),
            "summary_strategy": adapter.get("metadata_rules", {}).get("summary", ""),
            "cadence": adapter.get("release_cadence", ""),
            "checklist": adapter.get("checklist", []),
            "package_rules": adapter.get("package_rules", {}),
        },
    }


def create_platform_feedback_backflow(storage: LocalStorage, payload: dict[str, Any]) -> dict[str, Any]:
    platform_id = _platform_id(str(payload.get("platform") or payload.get("platform_id") or "qidian"))
    spec = DEFAULT_PLATFORM_STRATEGIES.get(platform_id, DEFAULT_PLATFORM_STRATEGIES["qidian"])
    project_id = str(payload.get("project_id") or "local-system")
    signals = payload.get("signals") if isinstance(payload.get("signals"), list) else []
    asset = _feedback_backflow_asset(platform_id, spec, project_id=project_id, signals=signals, workspace_path=str(payload.get("workspace_path") or ""))
    return _write(storage, asset)


def _profile_asset(platform_id: str, spec: dict[str, Any]) -> PlatformProfile:
    return PlatformProfile(
        id=f"platform-profile-{platform_id}",
        title=f"{spec['platform_name']} Platform Profile",
        source="platform-strategy-defaults",
        tags=["platform-profile", platform_id],
        content={
            "platform_id": platform_id,
            "platform_name": spec["platform_name"],
            "business_model": spec["business_model"],
            "update_frequency": "daily" if platform_id in {"fanqie", "feilu"} else "stable_serial",
            "reader_expectation": spec["reader_expectation"],
            "chapter_length_range": spec["chapter_length_range"],
            "review_risks": spec["review_risks"],
            "genre_fit": spec["genre_fit"],
            "style_tendency": spec["style_tendency"],
            "strategy_axes": spec["strategy_axes"],
            "core_strategy": _core_strategy_sentence(spec),
        },
        metadata={"project_id": "global", "workspace_path": "", "use_in_generation_rag": False, "platform_strategy_os": True},
    )


def _rhythm_asset(platform_id: str, spec: dict[str, Any]) -> PlatformRhythmRule:
    return PlatformRhythmRule(
        id=f"platform-rhythm-rule-{platform_id}",
        title=f"{spec['platform_name']} rhythm rule",
        source=f"platform-profile-{platform_id}",
        tags=["platform-rhythm-rule", platform_id],
        content={
            "rule_id": f"rhythm-{platform_id}",
            "platform_id": platform_id,
            "scope": "outline/chapter/prose",
            "strategy_axes": spec["strategy_axes"],
            "chapter_length_range": spec["chapter_length_range"],
            "beat_cadence": spec["beat_cadence"],
            "payoff_cadence": spec["payoff_cadence"],
            "hook_policy": spec["hook_policy"],
            "paywall_policy": spec["paywall_policy"],
            "prohibited_patterns": spec["review_risks"],
            "priority": 10,
        },
        metadata={"project_id": "global", "workspace_path": "", "use_in_generation_rag": False, "platform_strategy_os": True},
        references=[f"platform-profile-{platform_id}"],
    )


def _opening_gate_asset(platform_id: str, spec: dict[str, Any]) -> PlatformOpeningGate:
    return PlatformOpeningGate(
        id=f"platform-opening-gate-{platform_id}",
        title=f"{spec['platform_name']} opening gate",
        source=f"platform-profile-{platform_id}",
        tags=["platform-opening-gate", platform_id],
        content={
            "gate_id": f"opening-{platform_id}",
            "platform_id": platform_id,
            "required_signals": spec["opening_signals"],
            "score_thresholds": {"pass": 70, "warn": 55, "block": 40},
            "fail_conditions": spec["review_risks"][:4],
            "revision_hints": [f"强化{item}" for item in spec["opening_signals"][:3]],
        },
        metadata={"project_id": "global", "workspace_path": "", "use_in_generation_rag": False, "platform_strategy_os": True},
        references=[f"platform-profile-{platform_id}", f"platform-rhythm-rule-{platform_id}"],
    )


def _chapter_gate_asset(platform_id: str, spec: dict[str, Any]) -> PlatformChapterGate:
    return PlatformChapterGate(
        id=f"platform-chapter-gate-{platform_id}",
        title=f"{spec['platform_name']} chapter gate",
        source=f"platform-profile-{platform_id}",
        tags=["platform-chapter-gate", platform_id],
        content={
            "gate_id": f"chapter-{platform_id}",
            "platform_id": platform_id,
            "required_beats": spec["chapter_beats"],
            "density_targets": {"required_beat_min": max(3, min(5, len(spec["chapter_beats"]))), "payoff_per_chapter": 1, "hook_per_chapter": 1},
            "ending_hook": spec["hook_policy"],
            "word_budget": spec["chapter_length_range"],
            "blocking_rules": spec["review_risks"][:4],
        },
        metadata={"project_id": "global", "workspace_path": "", "use_in_generation_rag": False, "platform_strategy_os": True},
        references=[f"platform-profile-{platform_id}", f"platform-rhythm-rule-{platform_id}"],
    )


def _publish_adapter_asset(platform_id: str, spec: dict[str, Any]) -> PlatformPublishAdapter:
    return PlatformPublishAdapter(
        id=f"platform-publish-adapter-{platform_id}",
        title=f"{spec['platform_name']} publish adapter",
        source=f"platform-profile-{platform_id}",
        tags=["platform-publish-adapter", platform_id],
        content={
            "adapter_id": f"publish-{platform_id}",
            "platform_id": platform_id,
            "package_rules": {"chapter_length_range": spec["chapter_length_range"], "payoff_cadence": spec["payoff_cadence"], "paywall_policy": spec["paywall_policy"]},
            "metadata_rules": {"title": spec["publish_checklist"][0], "summary": spec["publish_checklist"][1], "chapter_note": spec["publish_checklist"][-1]},
            "release_cadence": "daily" if platform_id in {"fanqie", "feilu"} else "stable_serial",
            "checklist": spec["publish_checklist"],
            "export_contract": {"format": "local_release_package", "requires_publish_gate": True, "requires_platform_strategy_pack": True},
            "created_at": utc_now(),
        },
        metadata={"project_id": "global", "workspace_path": "", "use_in_generation_rag": False, "platform_strategy_os": True},
        references=[f"platform-profile-{platform_id}", f"platform-chapter-gate-{platform_id}"],
    )


def _feedback_backflow_asset(platform_id: str, spec: dict[str, Any], *, project_id: str, signals: list[Any], workspace_path: str = "") -> PlatformFeedbackBackflow:
    resolved_project_id = project_id or "global"
    backflow_id = make_id("platform_feedback_backflow", f"{platform_id}-{resolved_project_id}")
    return PlatformFeedbackBackflow(
        id=backflow_id,
        title=f"{spec['platform_name']} feedback backflow",
        source=f"platform-profile-{platform_id}" if resolved_project_id == "global" else "platform-feedback-signals",
        tags=["platform-feedback-backflow", platform_id],
        content={
            "backflow_id": backflow_id,
            "platform_id": platform_id,
            "project_id": resolved_project_id,
            "signal_mapping": _feedback_signal_mapping(platform_id, spec),
            "input_signals": signals,
            "plan_adjustments": _platform_plan_adjustments(platform_id, spec, signals),
            "weight_updates": _platform_weight_updates(platform_id, spec, signals),
            "created_at": utc_now(),
        },
        metadata={"project_id": resolved_project_id, "workspace_path": workspace_path, "use_in_generation_rag": False, "platform_strategy_os": True},
        references=[f"platform-profile-{platform_id}"] if resolved_project_id == "global" else [],
    )


def _outline_strategy(platform_id: str, spec: dict[str, Any], topic: str, genre: str) -> dict[str, Any]:
    return {
        "platform_id": platform_id,
        "topic": topic,
        "genre": genre,
        "reader_promise_shape": spec["reader_expectation"][:3],
        "act_design": _act_design(platform_id, spec),
        "pacing": spec["beat_cadence"],
        "volume_goals": [f"{spec['platform_name']}：{axis}" for axis in spec["strategy_axes"]],
        "opening_requirements": spec["opening_signals"],
        "risk_controls": spec["review_risks"],
    }


def _chapter_strategy(platform_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "platform_id": platform_id,
        "required_beats": spec["chapter_beats"],
        "beat_cadence": spec["beat_cadence"],
        "payoff_cadence": spec["payoff_cadence"],
        "ending_hook": spec["hook_policy"],
        "word_budget": spec["chapter_length_range"],
        "retention_focus": spec["retention_focus"],
    }


def _prose_strategy(platform_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "platform_id": platform_id,
        "style_tendency": spec["style_tendency"],
        "sentence_policy": "short-direct" if platform_id in {"fanqie", "feilu"} else "stable-controlled",
        "information_policy": "low-barrier" if platform_id in {"fanqie", "zhihu_yanxuan"} else "layered",
        "prohibited_patterns": spec["review_risks"],
    }


def _validation_policy(platform_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "platform_id": platform_id,
        "opening_gate_id": f"opening-{platform_id}",
        "chapter_gate_id": f"chapter-{platform_id}",
        "retention_metrics": spec["retention_focus"],
        "publish_checklist": spec["publish_checklist"],
        "blocking_if_missing": spec["opening_signals"][:2],
    }


def _act_design(platform_id: str, spec: dict[str, Any]) -> list[dict[str, Any]]:
    if platform_id == "qidian":
        return [{"act": 1, "goal": "建立世界规则和成长承诺"}, {"act": 2, "goal": "扩展世界和付费留存主线"}, {"act": 3, "goal": "阶段收益兑现并打开下一卷"}]
    if platform_id == "fanqie":
        return [{"act": 1, "goal": "低门槛强钩子进入冲突"}, {"act": 2, "goal": "高频反转和情绪反馈"}, {"act": 3, "goal": "强爽点兑现并快速开启新问题"}]
    if platform_id == "feilu":
        return [{"act": 1, "goal": "一句话强设定和身份差"}, {"act": 2, "goal": "密集爽点和设定收益"}, {"act": 3, "goal": "更大身份差和奖励升级"}]
    if platform_id == "jinjiang":
        return [{"act": 1, "goal": "建立人设吸引力和关系张力"}, {"act": 2, "goal": "推进关系误解、吸引和情绪抉择"}, {"act": 3, "goal": "兑现关系阶段变化"}]
    if platform_id == "zhihu_yanxuan":
        return [{"act": 1, "goal": "首段现实问题和异常证据"}, {"act": 2, "goal": "证据链推进与反转"}, {"act": 3, "goal": "短中篇答案收束和最终反转"}]
    return [{"act": 1, "goal": "建立主题意象和人物困境"}, {"act": 2, "goal": "结构推进与人物复杂度"}, {"act": 3, "goal": "主题表达和结构完整收束"}]


def _feedback_signal_mapping(platform_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "low_completion_rate": spec["retention_focus"][0],
        "weak_comment_emotion": spec["retention_focus"][1 if len(spec["retention_focus"]) > 1 else 0],
        "drop_after_opening": spec["opening_signals"][0],
        "chapter_end_drop": spec["hook_policy"],
        "positive_signal": spec["payoff_cadence"],
    }


def _platform_plan_adjustments(platform_id: str, spec: dict[str, Any], signals: list[Any]) -> list[dict[str, Any]]:
    values = [str(item).lower() for item in signals]
    rows = [{"field": "platform_pacing", "change": spec["beat_cadence"][0]}]
    if any("drop" in item or "流失" in item or "留存" in item for item in values):
        rows.append({"field": "chapter_hook", "change": spec["hook_policy"]})
    if any("slow" in item or "慢" in item for item in values):
        rows.append({"field": "opening", "change": f"强化{spec['opening_signals'][0]}"})
    return rows


def _platform_weight_updates(platform_id: str, spec: dict[str, Any], signals: list[Any]) -> list[dict[str, Any]]:
    rows = [{"target": item, "delta": 0.05, "reason": "platform strategy reinforcement"} for item in spec["strategy_axes"][:2]]
    if signals:
        rows.append({"target": "retention_risk", "delta": -0.08, "reason": "platform feedback requires mitigation"})
    return rows


def _retention_score(platform_id: str, metrics: dict[str, Any], feedback: list[Any]) -> tuple[int, list[dict[str, Any]]]:
    score = 0
    signals: list[dict[str, Any]] = []
    completion = _float(metrics.get("completion_rate"), 1.0)
    follow = _float(metrics.get("follow_read_rate"), 1.0)
    reversal_gap = _float(metrics.get("reversal_gap_chapters"), 0.0)
    payoff_gap = _float(metrics.get("payoff_gap_chapters"), 0.0)
    if completion < 0.55:
        score += 30
        signals.append({"signal": "low_completion_rate", "value": completion})
    if follow < 0.45:
        score += 30
        signals.append({"signal": "low_follow_read_rate", "value": follow})
    if platform_id in {"fanqie", "zhihu_yanxuan"} and reversal_gap > 1:
        score += 20
        signals.append({"signal": "reversal_gap_too_long", "value": reversal_gap})
    if platform_id in {"qidian", "feilu"} and payoff_gap > 3:
        score += 20
        signals.append({"signal": "payoff_gap_too_long", "value": payoff_gap})
    for item in feedback:
        text = str(item).lower()
        if any(word in text for word in ["慢", "无聊", "看不懂", "水", "boring", "slow", "confusing"]):
            score += 10
            signals.append({"signal": "negative_feedback", "value": str(item)[:120]})
    return min(100, score), signals


def _retention_mitigation(pack_content: dict[str, Any], signals: list[dict[str, Any]]) -> list[str]:
    strategy = pack_content.get("chapter_strategy", {}) if isinstance(pack_content.get("chapter_strategy"), dict) else {}
    validation = pack_content.get("validation_policy", {}) if isinstance(pack_content.get("validation_policy"), dict) else {}
    rows = [f"恢复平台节奏：{item}" for item in _strings(strategy.get("beat_cadence"))[:3]]
    rows.extend([f"补强门禁项：{item}" for item in _strings(validation.get("blocking_if_missing"))])
    if not rows:
        rows.append("review platform opening and chapter gate before next generation")
    return _dedupe(rows + [f"针对信号修复：{item.get('signal')}" for item in signals])


def _detected_signals(text: str, required: list[str]) -> list[str]:
    normalized = text.lower()
    found: list[str] = []
    keyword_map = {
        "成长": ["成长", "升级", "修炼", "收益", "level"],
        "世界": ["世界", "规则", "设定", "world"],
        "主线": ["主线", "目标", "义务", "危机"],
        "情绪": ["愤怒", "委屈", "痛", "爽", "情绪"],
        "反转": ["反转", "真相", "没想到", "原来"],
        "身份": ["身份", "地位", "差距", "压制"],
        "关系": ["关系", "误会", "吸引", "互动"],
        "现实": ["现实", "证据", "合同", "家庭", "职场"],
        "主题": ["主题", "意象", "语言", "结构"],
        "钩子": ["钩子", "悬念", "问题", "下一章"],
    }
    for item in required:
        if item in text:
            found.append(item)
            continue
        if any(any(keyword in normalized for keyword in keywords) for key, keywords in keyword_map.items() if key in item):
            found.append(item)
    return _dedupe(found)


def _gate_score(signals: list[str], required: list[str], *, text: str, platform_id: str, opening: bool) -> int:
    if not required:
        return 100
    score = int((len(signals) / len(required)) * 80)
    if opening and platform_id in {"fanqie", "zhihu_yanxuan"} and len(text) <= 800 and any(item in signals for item in required[:2]):
        score += 10
    if not opening and any(word in text for word in ["下一章", "然而", "可他", "谁也没想到", "门外"]):
        score += 10
    return min(100, score)


def _threshold(gate: dict[str, Any], key: str, fallback: int) -> int:
    content = gate.get("content", gate) if isinstance(gate, dict) else {}
    thresholds = content.get("score_thresholds", {}) if isinstance(content.get("score_thresholds", {}), dict) else {}
    return int(thresholds.get(key, fallback) or fallback)


def _payload_text(payload: dict[str, Any]) -> str:
    return "\n".join(str(payload.get(key) or "") for key in ["text", "opening_text", "chapter_text", "outline_text", "summary"] if str(payload.get(key) or "").strip())


def _platform_id(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return PLATFORM_ALIASES.get(normalized, PLATFORM_ALIASES.get(str(value or "").strip(), normalized or "qidian"))


def _find_platform_asset(storage: LocalStorage, asset_type: str, platform_id: str) -> dict[str, Any] | None:
    for row in _assets_by_type(storage, "platforms", {asset_type}, limit=1000):
        if str(row["content"].get("platform_id", "")) == platform_id:
            return row["asset"]
    return None


def _assets_by_type(storage: LocalStorage, category: str, asset_types: set[str], *, limit: int = 500) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json(category)):
        if len(rows) >= limit:
            break
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") not in asset_types:
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
        "title": data.get("title", ""),
        "content": content,
        "metadata": metadata,
        "asset": data,
    }


def _write(storage: LocalStorage, asset: Any) -> dict[str, Any]:
    data = asset.to_dict()
    _ensure_valid(data)
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": storage.read_json(path)}


def _ensure_valid(data: dict[str, Any]) -> None:
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))


def _stable_platform_asset_id(prefix: str, *parts: str) -> str:
    seed = "|".join(str(part) for part in parts if str(part).strip())
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
    label = slugify("-".join(str(part) for part in parts if str(part).strip())[:96], prefix)
    return f"{slugify(prefix)}-{label}-{digest}"


def _trim_asset(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": asset.get("id", ""),
        "type": asset.get("type", ""),
        "title": asset.get("title", ""),
        "content": asset.get("content", {}) if isinstance(asset.get("content"), dict) else {},
    }


def _core_strategy_sentence(spec: dict[str, Any]) -> str:
    return " / ".join(str(item) for item in spec["reader_expectation"][:4])


def _strings(value: Any) -> list[str]:
    if isinstance(value, list):
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
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _display_path(root: Path, path: str | Path) -> str:
    candidate = Path(path)
    try:
        return str(candidate.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(candidate)
