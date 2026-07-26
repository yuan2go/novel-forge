from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.agents import runtime_profile_for_skill
from novel_forge.modules.common import resolve_path
from novel_forge.modules.agent_runs import ensure_agent_contract, record_agent_event, start_agent_run
from novel_forge.schemas import BaseAsset, ClaudeCodeHandoff
from novel_forge.storage.local import LocalStorage

COMMON_CONTEXT_FILES = [
    "AGENTS.md",
    "docs/00-product/copyright-and-compliance.md",
    "docs/03-schemas/schema-index.md",
    "docs/09-skills/agent-skill-map.md",
]

ANALYSIS_HANDOFF_DEFINITIONS = {
    "web_fiction_business": {
        "operation": "hot_novel_business_deconstruction",
        "skill": "hot-novel-business-deconstruction",
        "expected_output_type": "web_fiction_business_analysis_report",
        "expected_output_dir": "data/analysis",
        "title": "Claude Code web fiction business analysis",
        "purpose": "extract abstract commercial structure, reader promise, hooks, pacing, and payoff loops",
        "fallback_categories": ["cleaned", "raw", "decompositions"],
        "skill_files": [
            "skills/hot-novel-business-deconstruction/SKILL.md",
            "skills/anti-copy-abstraction/SKILL.md",
        ],
        "acceptance": [
            "Output type is web_fiction_business_analysis_report and passes schema validation.",
            "Report contains platform_pattern, reader_promise, hook_system, payoff_loop, pacing_model, monetization_nodes, abstraction_boundary, and reusable_assets.",
        ],
    },
    "published_fiction": {
        "operation": "published_fiction_craft_analysis",
        "skill": "published-fiction-craft-analysis",
        "expected_output_type": "published_fiction_analysis_report",
        "expected_output_dir": "data/analysis",
        "title": "Claude Code published fiction craft analysis",
        "purpose": "extract abstract scene craft, narrative distance, character arc, subtext, and transferable techniques",
        "fallback_categories": ["cleaned", "raw", "decompositions"],
        "skill_files": [
            "skills/published-fiction-craft-analysis/SKILL.md",
            "skills/anti-copy-abstraction/SKILL.md",
        ],
        "acceptance": [
            "Output type is published_fiction_analysis_report and passes schema validation.",
            "Report contains craft_dimensions, scene_design, character_arc, narrative_distance, language_texture, transferable_techniques, and do_not_copy.",
        ],
    },
    "classic_literary": {
        "operation": "classic_literary_depth_analysis",
        "skill": "classic-literary-depth-analysis",
        "expected_output_type": "classic_literary_analysis_report",
        "expected_output_dir": "data/analysis",
        "title": "Claude Code classic literary depth analysis",
        "purpose": "extract abstract theme systems, symbol functions, social relation models, and fate curves",
        "fallback_categories": ["cleaned", "raw", "decompositions"],
        "skill_files": [
            "skills/classic-literary-depth-analysis/SKILL.md",
            "skills/anti-copy-abstraction/SKILL.md",
        ],
        "acceptance": [
            "Output type is classic_literary_analysis_report and passes schema validation.",
            "Report contains deep_structure, theme_system, symbol_system, social_relation_model, fate_curve, non_transferable_elements, and transferable_abstractions.",
        ],
    },
    "analysis_conversion": {
        "operation": "analysis_to_asset_conversion",
        "skill": "analysis-to-asset-conversion",
        "expected_output_type": "analysis_conversion_report",
        "expected_output_dir": "data/analysis",
        "title": "Claude Code analysis-to-asset conversion",
        "purpose": "convert an analysis report into safe abstract creative assets and rejected high-risk items",
        "fallback_categories": ["analysis", "decompositions"],
        "skill_files": [
            "skills/analysis-to-asset-conversion/SKILL.md",
            "skills/anti-copy-abstraction/SKILL.md",
        ],
        "acceptance": [
            "Output type is analysis_conversion_report and passes schema validation.",
            "Report records source_report_id, conversion_targets, created_assets, rejected_items, reuse_scope, copyright_risk, and abstraction_level.",
        ],
    },
}


def create_deconstruction_handoff(
    storage: LocalStorage,
    input_path: str | None = None,
    genre: str = "",
    target_reader: str = "",
    purpose: str = "",
) -> Path:
    source_path = _resolve_input(storage, input_path, fallback_categories=["cleaned"])
    source_asset = storage.read_asset(source_path)
    payload = {
        "genre": genre,
        "target_reader": target_reader,
        "purpose": purpose or "extract abstract commercial and narrative mechanisms from a web novel reference",
        "source_asset": _asset_summary(storage, source_path, source_asset),
    }
    return _write_handoff(
        storage=storage,
        operation="hot_novel_deconstruction",
        skill="hot-novel-deconstruction",
        title=f"Claude Code hot novel deconstruction: {source_asset.title or source_asset.name}",
        source_path=source_path,
        source_asset=source_asset,
        payload=payload,
        expected_output_type="decomposition_report",
        expected_output_dir="data/decompositions",
        skill_files=[
            "skills/hot-novel-deconstruction/SKILL.md",
            "skills/anti-copy-abstraction/SKILL.md",
        ],
        instructions=[
            "Open this handoff in Claude Code and use Codex as the analysis model in the current operator session.",
            "Read the source asset from the referenced path; do not copy source prose into this handoff or downstream materials.",
            "Apply the hot-novel-deconstruction skill and keep the result at mechanism, structure, rhythm, and commercial logic level.",
            "Write one schema-backed DecompositionReport JSON asset under data/decompositions.",
            "Run make validate after writing the asset and record any validation failures in the handoff status if follow-up is needed.",
        ],
        acceptance_checks=[
            "Output type is decomposition_report and passes schema validation.",
            "Report contains summary, commercial_patterns, narrative_patterns, character_mechanisms, conflict_patterns, emotion_curve, and hook_patterns.",
            "Metadata declares an abstract-structure copyright boundary.",
            "No protected expression, names, settings, or source-specific plot sequence is reused as generation material.",
        ],
    )


def create_knowledge_handoff(
    storage: LocalStorage,
    input_path: str | None = None,
    discipline: str = "",
    credibility: str = "",
    scope: str = "",
    project_context: str = "",
) -> Path:
    source_path = _resolve_input(storage, input_path, fallback_categories=["cleaned", "raw", "knowledge"])
    source_asset = storage.read_asset(source_path)
    payload = {
        "discipline": discipline,
        "credibility": credibility,
        "scope": scope or "convert multidisciplinary knowledge into story-safe constraints and review checks",
        "project_context": project_context,
        "source_asset": _asset_summary(storage, source_path, source_asset),
    }
    return _write_handoff(
        storage=storage,
        operation="multidisciplinary_knowledge_parse",
        skill="multidisciplinary-knowledge",
        title=f"Claude Code multidisciplinary knowledge parse: {source_asset.title or source_asset.name}",
        source_path=source_path,
        source_asset=source_asset,
        payload=payload,
        expected_output_type="knowledge_card",
        expected_output_dir="data/knowledge",
        skill_files=[
            "skills/multidisciplinary-knowledge/SKILL.md",
            "skills/quality-review/SKILL.md",
        ],
        instructions=[
            "Open this handoff in Claude Code and use Codex as the analysis model in the current operator session.",
            "Read the source asset from the referenced path; keep domain facts traceable without dumping raw exposition into story output.",
            "Apply the multidisciplinary-knowledge skill to convert concepts into story functions, constraints, conflict generators, and review checks.",
            "Write one schema-backed KnowledgeCard JSON asset under data/knowledge.",
            "Run make validate after writing the asset and record any validation failures in the handoff status if follow-up is needed.",
        ],
        acceptance_checks=[
            "Output type is knowledge_card and passes schema validation.",
            "KnowledgeCard content includes principles and story-safe constraints or checks derived from the source.",
            "Metadata declares an abstract-structure or knowledge-transformation copyright boundary.",
            "The output avoids high-risk operational advice, unverifiable certainty, and exposition dumps intended for direct prose insertion.",
        ],
    )


def create_analysis_handoff(
    storage: LocalStorage,
    input_path: str | None = None,
    analysis_type: str = "web_fiction_business",
    workspace_path: str | None = None,
    purpose: str = "",
) -> Path:
    definition = _analysis_definition(analysis_type)
    source_path = _resolve_input(storage, input_path, fallback_categories=list(definition["fallback_categories"]))
    source_asset = storage.read_asset(source_path)
    payload = {
        "analysis_type": analysis_type,
        "purpose": purpose or str(definition["purpose"]),
        "workspace_path": workspace_path or source_asset.metadata.get("workspace_path", ""),
        "source_asset": _asset_summary(storage, source_path, source_asset),
        "conversion_policy": "analysis reports are not generation RAG inputs; convert into abstract assets first",
    }
    return _write_handoff(
        storage=storage,
        operation=str(definition["operation"]),
        skill=str(definition["skill"]),
        title=f"{definition['title']}: {source_asset.title or source_asset.name}",
        source_path=source_path,
        source_asset=source_asset,
        payload=payload,
        expected_output_type=str(definition["expected_output_type"]),
        expected_output_dir=str(definition["expected_output_dir"]),
        skill_files=list(definition["skill_files"]),
        instructions=[
            "Open this handoff in Claude Code and use Codex as the analysis model in the current operator session.",
            "Read the source asset from the referenced path; do not copy source prose into this handoff or downstream assets.",
            "Apply the recorded analysis skill and keep the result at abstract mechanism, craft, structure, or template level.",
            f"Write one schema-backed {definition['expected_output_type']} JSON asset under {definition['expected_output_dir']}.",
            "Set metadata.use_in_generation_rag to false on the analysis report.",
            "Run make validate after writing the asset and record any validation failures in the handoff status if follow-up is needed.",
        ],
        acceptance_checks=[
            *list(definition["acceptance"]),
            "Metadata declares an abstract-structure copyright boundary.",
            "No protected expression, names, settings, or source-specific plot sequence is reused as generation material.",
            "High-risk source material is marked for human review before conversion.",
        ],
    )


def _write_handoff(
    storage: LocalStorage,
    operation: str,
    skill: str,
    title: str,
    source_path: Path,
    source_asset: BaseAsset,
    payload: dict[str, Any],
    expected_output_type: str,
    expected_output_dir: str,
    skill_files: list[str],
    instructions: list[str],
    acceptance_checks: list[str],
) -> Path:
    agent_runtime = runtime_profile_for_skill(skill)
    contract = ensure_agent_contract(
        storage,
        skill=skill,
        operation=operation,
        input_types=[source_asset.type],
        output_types=[expected_output_type],
        quality_gates=[
            {"gate": "schema_validation", "required": True, "expected_output_type": expected_output_type},
            {"gate": "acceptance_checks", "required": True, "count": len(acceptance_checks)},
            {"gate": "human_execution", "required": True, "runtime": "claude-code", "model": "codex"},
        ],
    )
    agent_run = start_agent_run(
        storage,
        skill=skill,
        operation=operation,
        input_assets=[source_path],
        status="waiting_human",
        contract_path=contract["path"],
        model_provider="claude-code",
        model_name="codex",
        prompt_version=f"{skill}:0.1.0",
        human_gate={"required": True, "status": "waiting_operator", "reason": "Claude Code handoff requires manual execution"},
        evidence={"expected_output_type": expected_output_type, "expected_output_dir": expected_output_dir},
    )
    input_files = [
        {
            "path": _relative_path(storage, source_path),
            "role": "source_asset",
            "must_read": True,
            "content_policy": "reference by path only; do not copy source text into this handoff",
        },
        *[
            {
                "path": path,
                "role": "skill" if path.startswith("skills/") else "governance",
                "must_read": True,
            }
            for path in [*skill_files, *COMMON_CONTEXT_FILES]
        ],
    ]
    context = {
        "runtime": "claude-code",
        "runtime_model": "codex",
        "skill": skill,
        "agent_runtime": agent_runtime,
        "expected_output_type": expected_output_type,
        "expected_output_dir": expected_output_dir,
        "validation_command": "make validate",
    }
    handoff_packet = _manual_claude_code_handoff_packet(
        operation, payload, context
    )
    asset = ClaudeCodeHandoff(
        title=title,
        source=source_asset.id,
        tags=["claude-code-handoff", "codex", skill, operation],
        content={
            "operation": operation,
            "runtime": "claude-code",
            "runtime_model": "codex",
            "skill": skill,
            "agent_runtime": agent_runtime,
            "agent_contract": {
                "id": contract["id"],
                "path": contract["path"],
            },
            "agent_run": {
                "id": agent_run["asset"]["content"]["run_id"],
                "asset_id": agent_run["asset"]["id"],
                "path": agent_run["path"],
                "status": agent_run["asset"]["content"]["status"],
            },
            "status": "pending",
            "input_files": input_files,
            "source_asset": _asset_summary(storage, source_path, source_asset),
            "expected_output_type": expected_output_type,
            "expected_output_dir": expected_output_dir,
            "instructions": [
                *instructions,
                f"Operate under the {agent_runtime['agent']} runtime profile and tool allowlist recorded in this handoff.",
            ],
            "acceptance_checks": [
                *acceptance_checks,
                "Output records input files, schema type, output path, and validation status.",
                "Agent runtime permission profile and tool allowlist were respected.",
            ],
            "handoff_packet": handoff_packet,
            "manual_execution": {
                "operator": "Claude Code",
                "model": "Codex",
                "write_output_to": expected_output_dir,
                "validation_command": "make validate",
            },
        },
        metadata={
            "model": "claude-code-manual-handoff",
            "runtime_model": "codex",
            "agent_role": agent_runtime["agent"],
            "permission_profile": agent_runtime["permission_profile"],
            "tool_allowlist": agent_runtime["allowed_tools"],
            "allowed_write_types": agent_runtime["allowed_write_types"],
            "agent_contract_id": contract["id"],
            "agent_contract_path": contract["path"],
            "agent_run_id": agent_run["asset"]["content"]["run_id"],
            "agent_run_asset_id": agent_run["asset"]["id"],
            "agent_run_path": agent_run["path"],
            "copyright_boundary": "handoff references source files only; analysis output must stay at abstract structure or transformed knowledge level",
            "automated_model_call": False,
            "external_api": False,
        },
        references=[
            source_asset.id,
            _relative_path(storage, source_path),
            contract["id"],
            contract["path"],
            agent_run["asset"]["content"]["run_id"],
            agent_run["path"],
            *skill_files,
        ],
    )
    path = storage.write_asset("runs", asset)
    record_agent_event(
        storage,
        agent_run_path=agent_run["path"],
        event_type="handoff.created",
        status="waiting_human",
        message=f"Claude Code handoff created for {operation}",
        payload={"handoff_path": _relative_path(storage, path), "expected_output_type": expected_output_type},
    )
    return path


def _manual_claude_code_handoff_packet(
    operation: str,
    payload: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Build a deterministic packet; this function launches no Agent process."""

    return {
        "provider": "claude-code",
        "model": "manual-claude-code-runtime",
        "operation": operation,
        "status": "manual_handoff_required",
        "external_api": False,
        "automated_model_call": False,
        "payload": payload,
        "context": context,
        "instructions": [
            "Read the referenced project files before producing output.",
            "Write results as schema-backed JSON assets through Novel Forge CLI or storage rules.",
            "Do not treat this packet as permission to call external APIs or bypass validation.",
            "Run relevant validation after writing outputs.",
        ],
        "expected_return": {
            "asset_path": "path to a schema-backed JSON asset",
            "validation_command": "make validate or a narrower relevant check",
        },
    }


def _resolve_input(storage: LocalStorage, input_path: str | None, fallback_categories: list[str]) -> Path:
    if input_path:
        return resolve_path(storage.root, input_path)
    for category in fallback_categories:
        files = storage.list_json(category)
        if files:
            return files[-1]
    categories = ", ".join(f"data/{category}" for category in fallback_categories)
    raise FileNotFoundError(f"no input asset found; provide --input or create an asset in {categories}")


def _asset_summary(storage: LocalStorage, path: Path, asset: BaseAsset) -> dict[str, Any]:
    rights = asset.metadata.get("rights", {}) if isinstance(asset.metadata, dict) else {}
    return {
        "path": _relative_path(storage, path),
        "id": asset.id,
        "type": asset.type,
        "title": asset.title or asset.name,
        "source": asset.source,
        "tags": asset.tags,
        "version": asset.version,
        "content_fields": sorted(asset.content.keys()),
        "rights_authorization": rights.get("authorization", ""),
        "allow_downstream_generation": rights.get("allow_downstream_generation", False),
    }


def _analysis_definition(analysis_type: str) -> dict[str, Any]:
    key = analysis_type.strip().lower().replace("-", "_")
    aliases = {
        "web": "web_fiction_business",
        "web_fiction": "web_fiction_business",
        "hot_novel_business": "web_fiction_business",
        "published": "published_fiction",
        "published_fiction_craft": "published_fiction",
        "classic": "classic_literary",
        "classic_literary_depth": "classic_literary",
        "converter": "analysis_conversion",
        "conversion": "analysis_conversion",
        "analysis_to_asset": "analysis_conversion",
    }
    normalized = aliases.get(key, key)
    try:
        return ANALYSIS_HANDOFF_DEFINITIONS[normalized]
    except KeyError as exc:
        allowed = ", ".join(sorted(ANALYSIS_HANDOFF_DEFINITIONS))
        raise ValueError(f"unsupported analysis handoff type: {analysis_type}; allowed: {allowed}") from exc


def _relative_path(storage: LocalStorage, path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(storage.root))
    except ValueError:
        return str(resolved)
