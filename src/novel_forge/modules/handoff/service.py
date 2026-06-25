from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.agents import runtime_profile_for_skill
from novel_forge.model_adapters import ClaudeCodeAdapter
from novel_forge.modules.common import resolve_path
from novel_forge.schemas import BaseAsset, ClaudeCodeHandoff
from novel_forge.storage.local import LocalStorage

COMMON_CONTEXT_FILES = [
    "AGENTS.md",
    "docs/00-product/copyright-and-compliance.md",
    "docs/03-schemas/schema-index.md",
    "docs/09-skills/agent-skill-map.md",
]


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
    adapter = ClaudeCodeAdapter()
    agent_runtime = runtime_profile_for_skill(skill)
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
    handoff_packet = adapter.create_handoff_packet(operation, payload, context)
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
            "model": adapter.name,
            "runtime_model": "codex",
            "agent_role": agent_runtime["agent"],
            "permission_profile": agent_runtime["permission_profile"],
            "tool_allowlist": agent_runtime["allowed_tools"],
            "allowed_write_types": agent_runtime["allowed_write_types"],
            "copyright_boundary": "handoff references source files only; analysis output must stay at abstract structure or transformed knowledge level",
            "automated_model_call": False,
            "external_api": False,
        },
        references=[source_asset.id, _relative_path(storage, source_path), *skill_files],
    )
    return storage.write_asset("runs", asset)


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


def _relative_path(storage: LocalStorage, path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(storage.root))
    except ValueError:
        return str(resolved)
