from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.os_envelope import enforce_os_envelope, envelope_asset_metadata, is_production_environment
from novel_forge.modules.review_issue import persist_issue_candidates
from novel_forge.schemas import (
    GenreProfile,
    GenreRiskGate,
    GenreStrategyPack,
    GenreTemplateBinding,
    PlatformGenreFit,
    SubgenreMechanic,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage


SUPPORTED_GENRE_PROFILES: dict[str, dict[str, Any]] = {
    "xuanhuan": {
        "genre_name": "玄幻",
        "aliases": ["玄幻", "fantasy-cultivation"],
        "core_pleasures": ["成长跃迁", "体系升级", "强敌压迫", "资源争夺", "身份揭示"],
        "reader_promises": ["主角在清晰规则中持续变强", "每卷都有更高层级的世界和敌人"],
        "required_systems": ["power_scale", "resource_economy", "sect_or_faction_pressure"],
        "worldbuilding_requirements": ["等级边界明确", "资源稀缺有代价", "战力越级必须有条件"],
        "character_requirements": ["主角目标可长期追踪", "反派和同盟都服务成长压力"],
        "opening_signals": ["低位困境", "体系入口", "第一个可量化目标"],
        "chapter_beats": ["压迫", "选择", "代价", "突破", "新钩子"],
        "longform_risks": ["战力膨胀", "副本重复", "资源失去稀缺性"],
    },
    "urban": {
        "genre_name": "都市",
        "aliases": ["都市", "urban"],
        "core_pleasures": ["现实逆袭", "关系博弈", "职业爽点", "身份反差"],
        "reader_promises": ["现实场景中的可感知升级", "冲突贴近日常但回报放大"],
        "required_systems": ["status_ladder", "relationship_network", "career_or_business_engine"],
        "worldbuilding_requirements": ["城市资源网络明确", "行业规则可验证", "财富和权力路径有成本"],
        "character_requirements": ["主角欲望清晰", "配角关系能制造连续冲突"],
        "opening_signals": ["现实羞辱或损失", "隐藏能力或资源", "立即可见的翻盘机会"],
        "chapter_beats": ["现实压力", "资源调度", "反差亮相", "情绪回报", "新关系压力"],
        "longform_risks": ["外挂失控", "商业逻辑空转", "关系线重复"],
    },
    "mystery": {
        "genre_name": "悬疑",
        "aliases": ["悬疑", "刑侦", "密室", "mystery"],
        "core_pleasures": ["线索解码", "误导反转", "真相逼近", "智力公平"],
        "reader_promises": ["关键答案能被回看验证", "每个反转都来自已埋证据"],
        "required_systems": ["evidence_chain", "suspect_matrix", "reveal_schedule"],
        "worldbuilding_requirements": ["案件规则稳定", "证据来源可追溯", "警方/侦探权限有边界"],
        "character_requirements": ["嫌疑人动机成网", "侦探推理路径可复盘"],
        "opening_signals": ["异常现场", "不可解释矛盾", "第一条误导线索"],
        "chapter_beats": ["发现", "假设", "阻碍", "证伪", "新矛盾"],
        "longform_risks": ["线索不可回溯", "反转靠新增设定", "读者疲劳"],
    },
    "sci_fi": {
        "genre_name": "科幻",
        "aliases": ["科幻", "赛博朋克", "sci-fi", "science-fiction"],
        "core_pleasures": ["规则奇观", "技术代价", "文明尺度", "问题求解"],
        "reader_promises": ["核心设定持续产出剧情", "技术限制被公平遵守"],
        "required_systems": ["science_rule_set", "constraint_ledger", "societal_impact"],
        "worldbuilding_requirements": ["科技规则少而硬", "代价长期生效", "社会后果进入人物选择"],
        "character_requirements": ["人物选择承受规则代价", "立场冲突体现技术伦理"],
        "opening_signals": ["异常技术现象", "明确限制", "第一次代价"],
        "chapter_beats": ["规则暴露", "实验/行动", "副作用", "伦理选择", "尺度扩张"],
        "longform_risks": ["万能科技", "说明压过剧情", "设定自相矛盾"],
    },
    "historical": {
        "genre_name": "历史",
        "aliases": ["历史", "权谋", "historical"],
        "core_pleasures": ["权力博弈", "制度缝隙", "阵营重组", "历史压力"],
        "reader_promises": ["选择受时代限制", "胜利来自制度和人心的调度"],
        "required_systems": ["faction_network", "resource_map", "court_or_frontier_rules"],
        "worldbuilding_requirements": ["时代制度可解释", "派系利益清晰", "资源流向可追踪"],
        "character_requirements": ["主角策略有代价", "盟友背叛有利益逻辑"],
        "opening_signals": ["制度压迫", "派系站队", "一次小胜或失手"],
        "chapter_beats": ["局势变化", "筹码交换", "暗线推进", "代价显现", "权力钩子"],
        "longform_risks": ["资料堆砌", "权谋无成本", "派系关系混乱"],
    },
    "romance": {
        "genre_name": "言情",
        "aliases": ["言情", "关系向", "romance"],
        "core_pleasures": ["情感拉扯", "关系确认", "误会解除", "共同成长"],
        "reader_promises": ["关系推进有阶段", "情绪回报来自人物选择"],
        "required_systems": ["relationship_state", "emotional_obstacle", "trust_progression"],
        "worldbuilding_requirements": ["关系压力来自场景和身份", "外部事件服务情感变化"],
        "character_requirements": ["双方欲望与伤口互相作用", "关系状态每阶段可识别"],
        "opening_signals": ["强烈初遇矛盾", "互相误读", "无法回避的共同目标"],
        "chapter_beats": ["接近", "误读", "暴露脆弱", "退让或靠近", "情绪钩子"],
        "longform_risks": ["误会拖延", "人物工具化", "情绪循环不升级"],
    },
    "fantasy": {
        "genre_name": "奇幻",
        "aliases": ["奇幻", "fantasy"],
        "core_pleasures": ["异世界规则", "冒险同盟", "魔法代价", "命运抉择"],
        "reader_promises": ["世界规则能反复驱动冲突", "冒险推进揭示更大秩序"],
        "required_systems": ["magic_rule", "quest_chain", "faction_or_race_tension"],
        "worldbuilding_requirements": ["魔法边界明确", "地理/种族/信仰影响剧情"],
        "character_requirements": ["队伍功能互补", "人物信念与世界规则冲突"],
        "opening_signals": ["世界异常", "任务召唤", "规则代价"],
        "chapter_beats": ["探索", "规则应用", "队伍摩擦", "局部胜利", "更大威胁"],
        "longform_risks": ["设定过散", "任务串珠", "魔法便利化"],
    },
    "horror": {
        "genre_name": "恐怖",
        "aliases": ["恐怖", "诡异", "horror"],
        "core_pleasures": ["规则污染", "未知逼近", "禁忌代价", "生存压迫"],
        "reader_promises": ["恐惧规则逐步显形", "越理解越危险"],
        "required_systems": ["contamination_rule", "taboo_list", "safe_zone_decay"],
        "worldbuilding_requirements": ["怪异规则一致", "污染扩散可追踪", "避险手段有限"],
        "character_requirements": ["人物恐惧点具体", "求生选择制造道德代价"],
        "opening_signals": ["轻微异常", "第一次禁忌", "不可逆污染痕迹"],
        "chapter_beats": ["异常", "试探", "误判", "污染升级", "禁忌钩子"],
        "longform_risks": ["恐惧脱敏", "规则失效", "怪异万能"],
    },
    "realist": {
        "genre_name": "现实",
        "aliases": ["现实", "realist"],
        "core_pleasures": ["真实困境", "微小胜利", "关系修复", "社会观察"],
        "reader_promises": ["人物变化可信", "冲突来自真实压力"],
        "required_systems": ["social_pressure", "life_stage_goal", "relationship_repair"],
        "worldbuilding_requirements": ["行业/家庭/地域细节准确", "事件代价真实"],
        "character_requirements": ["选择受能力和处境限制", "成长不是简单爽文翻盘"],
        "opening_signals": ["具体生活困境", "不可回避关系", "一个可达成小目标"],
        "chapter_beats": ["压力", "尝试", "挫折", "微变", "现实钩子"],
        "longform_risks": ["缺少推进力", "说教", "情绪过平"],
    },
    "light_novel": {
        "genre_name": "轻小说",
        "aliases": ["轻小说", "light-novel"],
        "core_pleasures": ["鲜明设定", "角色互动", "轻快节奏", "情绪标签"],
        "reader_promises": ["角色魅力和设定趣味持续可见", "章节轻快但主线不断"],
        "required_systems": ["character_gimmick", "scene_comedy_engine", "arc_hook"],
        "worldbuilding_requirements": ["设定能快速理解", "场景服务互动", "规则不拖慢阅读"],
        "character_requirements": ["角色功能和魅力点明确", "关系动态可持续变化"],
        "opening_signals": ["一句话设定", "鲜明角色冲突", "轻快钩子"],
        "chapter_beats": ["设定碰撞", "角色反应", "小危机", "情绪回报", "下一互动钩子"],
        "longform_risks": ["角色标签空转", "主线过弱", "笑点重复"],
    },
}

SUBGENRE_MECHANICS: dict[str, dict[str, Any]] = {
    "mortal_flow": {"name": "凡人流", "genre_id": "xuanhuan", "mechanics": ["低资源成长", "谨慎决策", "越级代价"]},
    "overpowered": {"name": "无敌流", "genre_id": "xuanhuan", "mechanics": ["压倒性回报", "身份反差", "外部问题升级"]},
    "weird_cultivation": {"name": "诡异修仙", "genre_id": "xuanhuan", "mechanics": ["修行污染", "禁忌代价", "规则恐惧"]},
    "police_procedural": {"name": "刑侦", "genre_id": "mystery", "mechanics": ["程序约束", "证据链", "嫌疑网络"]},
    "locked_room": {"name": "密室", "genre_id": "mystery", "mechanics": ["空间约束", "不可能犯罪", "公平伏线"]},
    "cyberpunk": {"name": "赛博朋克", "genre_id": "sci_fi", "mechanics": ["技术异化", "公司权力", "身份/身体代价"]},
    "power_politics": {"name": "权谋", "genre_id": "historical", "mechanics": ["派系交换", "信息不对称", "制度缝隙"]},
    "relationship_driven": {"name": "关系向", "genre_id": "romance", "mechanics": ["情绪阶段", "信任推进", "共同选择"]},
}


def inspect_genre_catalog() -> dict[str, Any]:
    return {
        "genres": SUPPORTED_GENRE_PROFILES,
        "subgenres": SUBGENRE_MECHANICS,
        "count": len(SUPPORTED_GENRE_PROFILES),
    }


def build_genre_strategy_pack(
    storage: LocalStorage,
    *,
    genre: str,
    subgenre: str = "",
    project_id: str = "",
    platform_id: str = "local",
    title: str = "",
    environment: str = "",
    envelope: dict[str, Any] | None = None,
    source_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile_id = _resolve_genre_id(genre)
    profile = SUPPORTED_GENRE_PROFILES[profile_id]
    subgenre_id = _resolve_subgenre_id(subgenre, default_genre_id=profile_id)
    mechanic = SUBGENRE_MECHANICS.get(subgenre_id, _default_subgenre(profile_id))
    production = is_production_environment(environment or (envelope or {}).get("environment"))
    if production and not project_id and not (envelope or {}).get("project_id"):
        raise ValueError("project_id is required for production genre strategy packs")
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="build-genre-strategy-pack",
        project_id=project_id,
        task_type="genre_strategy",
        asset_type="genre_strategy_pack",
        source_policy=source_policy or {"raw_source_text_allowed": False, "generation_rag_allowed": True},
        environment=environment,
        require_for_production=True,
    )
    resolved_project_id = str(project_id or env.get("project_id") or "")
    metadata = {
        "project_id": resolved_project_id,
        "platform_id": platform_id,
        "content_intelligence_version": "v7",
        **envelope_asset_metadata(env),
    }
    genre_asset = GenreProfile(
        title=f"{profile['genre_name']} genre profile",
        tags=["genre-os", profile_id],
        content={
            "genre_id": profile_id,
            "genre_name": profile["genre_name"],
            "reader_promises": profile["reader_promises"],
            "core_pleasures": profile["core_pleasures"],
            "required_systems": profile["required_systems"],
            "common_risks": profile["longform_risks"],
            "status": "active",
        },
        metadata=metadata,
    )
    subgenre_asset = SubgenreMechanic(
        title=f"{mechanic['name']} mechanic",
        tags=["genre-os", profile_id, subgenre_id],
        content={
            "subgenre_id": subgenre_id,
            "genre_id": profile_id,
            "mechanics": mechanic["mechanics"],
            "opening_requirements": profile["opening_signals"],
            "chapter_beats": profile["chapter_beats"],
            "longform_risks": profile["longform_risks"],
            "anti_patterns": _anti_patterns(profile_id),
            "innovation_axes": _innovation_axes(profile_id),
        },
        metadata=metadata,
    )
    fit_asset = PlatformGenreFit(
        title=f"{platform_id} fit for {profile['genre_name']}",
        tags=["genre-os", "platform-fit", profile_id],
        content={
            "fit_id": make_id("platform_genre_fit", f"{platform_id}-{profile_id}-{subgenre_id}"),
            "platform_id": platform_id,
            "genre_id": profile_id,
            "subgenre_id": subgenre_id,
            "fit_score": _fit_score(platform_id, profile_id),
            "fit_reasons": _fit_reasons(platform_id, profile),
            "risk_controls": profile["longform_risks"],
        },
        metadata=metadata,
    )
    binding_asset = GenreTemplateBinding(
        title=f"{profile['genre_name']} template binding",
        tags=["genre-os", "template-binding", profile_id],
        content={
            "binding_id": make_id("genre_template_binding", f"{profile_id}-{subgenre_id}"),
            "genre_id": profile_id,
            "subgenre_id": subgenre_id,
            "template_bindings": {
                "outline": ["long-outline", "narrative-beat-design"],
                "chapter_plan": ["chapter-outline", "narrative-beat-design"],
                "review": ["quality-review", "review-issue-gate"],
            },
            "review_rule_refs": [f"genre:{profile_id}:core_pleasure", f"genre:{profile_id}:longform_risk"],
            "context_refs": ["genre_strategy_pack", "style_generation_policy", "quality_rubric_pack"],
        },
        metadata=metadata,
    )
    pack_asset = GenreStrategyPack(
        title=title or f"{profile['genre_name']} strategy pack",
        tags=["genre-os", "strategy-pack", profile_id, subgenre_id],
        content={
            "pack_id": make_id("genre_strategy_pack", f"{resolved_project_id}-{profile_id}-{subgenre_id}"),
            "project_id": resolved_project_id,
            "platform_id": platform_id,
            "genre_id": profile_id,
            "subgenre_id": subgenre_id,
            "core_pleasures": profile["core_pleasures"],
            "reader_promise": profile["reader_promises"],
            "required_systems": profile["required_systems"],
            "worldbuilding_requirements": profile["worldbuilding_requirements"],
            "character_requirements": profile["character_requirements"],
            "opening_signals": profile["opening_signals"],
            "chapter_beat_policy": {"default_beats": profile["chapter_beats"], "subgenre_mechanics": mechanic["mechanics"]},
            "longform_risks": profile["longform_risks"],
            "platform_fit": fit_asset.content,
            "review_rules": _review_rules(profile_id, profile, mechanic),
            "context_contract": {
                "allowed_context_asset_types": [
                    "genre_profile",
                    "subgenre_mechanic",
                    "genre_strategy_pack",
                    "platform_genre_fit",
                    "genre_template_binding",
                ],
                "raw_reference_text_allowed": False,
                "injection_role": "abstract_content_intelligence",
            },
        },
        metadata=metadata,
        references=[],
    )
    paths = {
        "genre_profile_path": _write_asset(storage, genre_asset),
        "subgenre_mechanic_path": _write_asset(storage, subgenre_asset),
        "platform_genre_fit_path": _write_asset(storage, fit_asset),
        "genre_template_binding_path": _write_asset(storage, binding_asset),
    }
    pack_asset.references = [*paths.values()]
    pack_path = _write_asset(storage, pack_asset)
    return {
        "genre_strategy_pack_path": pack_path,
        **paths,
        "asset": storage.read_json(resolve_path(storage.root, pack_path)),
        "envelope": env,
    }


def run_genre_risk_gate(
    storage: LocalStorage,
    *,
    strategy_pack_path: str | Path,
    target_path: str | Path | None = None,
    evidence: dict[str, Any] | None = None,
    environment: str = "",
    envelope: dict[str, Any] | None = None,
    persist_issues: bool = True,
) -> dict[str, Any]:
    if is_production_environment(environment or (envelope or {}).get("environment")) and not target_path:
        raise ValueError("target_path is required for production genre risk gates")
    pack_file = resolve_path(storage.root, strategy_pack_path)
    pack = storage.read_json(pack_file)
    content = pack.get("content", {}) if isinstance(pack.get("content"), dict) else {}
    project_id = str(content.get("project_id") or pack.get("metadata", {}).get("project_id") or "")
    env = enforce_os_envelope(
        storage,
        envelope_payload=envelope,
        operation="run-genre-risk-gate",
        project_id=project_id,
        task_type="genre_risk_gate",
        asset_type="genre_risk_gate",
        source_policy={"raw_source_text_allowed": False, "generation_rag_allowed": False},
        environment=environment,
        require_for_production=True,
    )
    target = _read_optional_target(storage, target_path)
    risks = _detect_risks(content, target, evidence or {})
    issue_paths: list[str] = []
    target_asset_id = str(target.get("id") or content.get("pack_id") or pack.get("id") or "")
    target_asset_type = str(target.get("type") or "genre_strategy_pack")
    target_asset_path = _display_path(storage.root, resolve_path(storage.root, target_path)) if target_path else _display_path(storage.root, pack_file)
    if persist_issues:
        issue_summary = persist_issue_candidates(
            storage,
            [
                {
                    "issue_type": "genre_risk",
                    "severity": risk["severity"],
                    "blocking": risk["blocking"],
                    "target_asset_id": target_asset_id,
                    "target_asset_type": target_asset_type,
                    "target_asset_path": target_asset_path,
                    "project_id": project_id,
                    "message": risk["message"],
                    "fix_suggestion": risk["fix_suggestion"],
                    "evidence_refs": [target_asset_path, _display_path(storage.root, pack_file)],
                }
                for risk in risks
                if risk["blocking"] or risk["severity"] in {"medium", "high", "critical"}
            ],
            source_system="genre_os.risk_gate",
        )
        issue_paths = [str(path) for path in issue_summary.get("issue_paths", [])]
    blocking_count = sum(1 for risk in risks if risk.get("blocking"))
    gate = GenreRiskGate(
        title=f"Genre risk gate for {target_asset_id or pack.get('id')}",
        source=target_asset_id,
        tags=["genre-os", "risk-gate", "blocking" if blocking_count else "passed"],
        content={
            "gate_id": make_id("genre_risk_gate", target_asset_id or pack.get("id", "")),
            "target_asset_id": target_asset_id,
            "target_asset_type": target_asset_type,
            "genre_id": str(content.get("genre_id") or ""),
            "risks": risks,
            "blocking_issue_count": blocking_count,
            "recommendation": "blocked" if blocking_count else "passed",
            "review_issue_paths": issue_paths,
        },
        metadata={"project_id": project_id, **envelope_asset_metadata(env)},
        references=[_display_path(storage.root, pack_file), target_asset_path, *issue_paths],
    )
    gate_path = _write_asset(storage, gate)
    return {"path": gate_path, "asset": storage.read_json(resolve_path(storage.root, gate_path)), "review_issues": issue_paths, "envelope": env}


def _resolve_genre_id(value: str) -> str:
    needle = str(value or "").strip().lower().replace("-", "_")
    for genre_id, profile in SUPPORTED_GENRE_PROFILES.items():
        aliases = [genre_id, *profile.get("aliases", [])]
        if needle in {str(alias).strip().lower().replace("-", "_") for alias in aliases}:
            return genre_id
    raise ValueError(f"unsupported genre: {value}")


def _resolve_subgenre_id(value: str, *, default_genre_id: str) -> str:
    needle = str(value or "").strip().lower().replace("-", "_")
    if not needle:
        return f"{default_genre_id}_core"
    for subgenre_id, mechanic in SUBGENRE_MECHANICS.items():
        aliases = [subgenre_id, mechanic.get("name", "")]
        if needle in {str(alias).strip().lower().replace("-", "_") for alias in aliases}:
            return subgenre_id
    return f"{default_genre_id}_{needle}"


def _default_subgenre(genre_id: str) -> dict[str, Any]:
    profile = SUPPORTED_GENRE_PROFILES[genre_id]
    return {"name": f"{profile['genre_name']}核心型", "genre_id": genre_id, "mechanics": profile["required_systems"]}


def _review_rules(genre_id: str, profile: dict[str, Any], mechanic: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"rule_id": f"{genre_id}:reader_promise", "check": "reader_promise_visible", "severity": "high", "blocking": True},
        {"rule_id": f"{genre_id}:required_systems", "check": "required_systems_present", "severity": "high", "blocking": True},
        {"rule_id": f"{genre_id}:beat_policy", "check": "chapter_beats_follow_policy", "severity": "medium", "blocking": False},
        {
            "rule_id": f"{genre_id}:longform_risk",
            "check": "longform_risks_have_controls",
            "severity": "high",
            "blocking": True,
            "risk_controls": [*profile["longform_risks"], *mechanic.get("mechanics", [])],
        },
    ]


def _detect_risks(pack_content: dict[str, Any], target: dict[str, Any], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    text = _target_text(target).lower()
    risks: list[dict[str, Any]] = []
    if not pack_content.get("core_pleasures"):
        risks.append(_risk("critical", "genre strategy pack is missing core pleasures", "Rebuild the pack with genre_profile evidence."))
    if not pack_content.get("required_systems"):
        risks.append(_risk("critical", "genre strategy pack is missing required systems", "Add required systems before outline/draft use."))
    opening_signals = [str(item).lower() for item in pack_content.get("opening_signals", [])]
    if target and opening_signals and not any(signal and signal in text for signal in opening_signals):
        risks.append(_risk("medium", "target does not visibly carry opening signals", "Revise the opening or chapter plan to expose genre signals."))
    missing_controls = [risk for risk in pack_content.get("longform_risks", []) if risk and risk not in str(evidence)]
    if len(missing_controls) >= 2:
        risks.append(_risk("high", f"longform risks lack mitigation evidence: {', '.join(missing_controls[:3])}", "Attach mitigation controls or update review rules."))
    if not risks:
        risks.append(_risk("info", "genre strategy evidence is complete enough for local gate", "No action required."))
    return risks


def _risk(severity: str, message: str, fix_suggestion: str) -> dict[str, Any]:
    return {"severity": severity, "blocking": severity in {"high", "critical"}, "message": message, "fix_suggestion": fix_suggestion}


def _target_text(target: dict[str, Any]) -> str:
    content = target.get("content", {}) if isinstance(target.get("content"), dict) else {}
    for key in ["text", "draft_text", "chapter_text", "summary", "body"]:
        if content.get(key):
            return str(content.get(key))
    return " ".join(str(value) for value in content.values() if isinstance(value, (str, int, float)))


def _read_optional_target(storage: LocalStorage, target_path: str | Path | None) -> dict[str, Any]:
    if not target_path:
        return {}
    return storage.read_json(resolve_path(storage.root, target_path))


def _anti_patterns(genre_id: str) -> list[str]:
    return {
        "mystery": ["反转靠新增设定", "线索不可回看验证"],
        "sci_fi": ["万能科技", "规则临时变更"],
        "romance": ["误会循环不升级", "关系推进无选择代价"],
        "horror": ["规则失效", "恐惧只靠描写音效"],
    }.get(genre_id, ["核心爽点不可见", "章节 beat 重复", "长篇风险无控制"])


def _innovation_axes(genre_id: str) -> list[str]:
    return {
        "xuanhuan": ["修行代价", "资源经济", "阶层压力"],
        "urban": ["行业机制", "关系网络", "现实议题"],
        "mystery": ["证据呈现方式", "嫌疑人关系结构", "推理视角"],
        "sci_fi": ["技术限制", "文明尺度", "伦理困境"],
        "historical": ["制度缝隙", "派系筹码", "边疆/朝堂双线"],
    }.get(genre_id, ["角色关系机制", "冲突结构", "平台节奏"])


def _fit_score(platform_id: str, genre_id: str) -> int:
    platform = platform_id.lower()
    if platform in {"local", "fixture", "manual"}:
        return 80
    if "qidian" in platform or "web" in platform:
        return 88 if genre_id in {"xuanhuan", "urban", "mystery", "sci_fi"} else 78
    return 75


def _fit_reasons(platform_id: str, profile: dict[str, Any]) -> list[str]:
    return [f"{platform_id} can inspect abstract genre signals", f"reader promise: {profile['reader_promises'][0]}"]


def _write_asset(storage: LocalStorage, asset: Any) -> str:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    return _display_path(storage.root, storage.write_asset_auto(asset))


def _display_path(root: Path, path: str | Path) -> str:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return str(resolved.relative_to(root)) if resolved.is_relative_to(root) else str(resolved)
