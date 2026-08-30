from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from novel_forge.modules.production_execution import default_capability_registry
from novel_forge.modules.source_authority.deconstruction import AnalyzerContract

from .methodologies import SourceMethodologyRegistry
from .profiling import LogicalDocumentScope, SourceContentType, canonical_hash


@dataclass(frozen=True, slots=True)
class AnalyzerMethodologySpec:
    dimension: str
    skill_id: str
    prompt_focus: str


@dataclass(frozen=True, slots=True)
class SourceAnalysisProfile:
    profile_id: str
    profile_version: str
    content_type: SourceContentType
    methodology_specs: tuple[AnalyzerMethodologySpec, ...]
    window_chunks: int
    max_analyzer_calls: int
    mkaos_capability: str
    abstraction_policy_version: str


@dataclass(frozen=True, slots=True)
class ResolvedAnalysisStrategy:
    profile_id: str
    profile_version: str
    content_type: SourceContentType
    routing_policy_version: str
    analyzers: tuple[AnalyzerContract, ...]
    window_chunks: int
    max_analyzer_calls: int
    mkaos_capability: str
    abstraction_policy_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "content_type": self.content_type.value,
            "routing_policy_version": self.routing_policy_version,
            "analyzers": [item.to_dict() for item in self.analyzers],
            "window_chunks": self.window_chunks,
            "max_analyzer_calls": self.max_analyzer_calls,
            "mkaos_capability": self.mkaos_capability,
            "abstraction_policy_version": self.abstraction_policy_version,
        }

    @property
    def fingerprint(self) -> str:
        return canonical_hash(self.to_dict())


def analysis_strategy_from_dict(
    payload: dict[str, Any], *, expected_fingerprint: str
) -> ResolvedAnalysisStrategy:
    try:
        strategy = ResolvedAnalysisStrategy(
            profile_id=str(payload["profile_id"]),
            profile_version=str(payload["profile_version"]),
            content_type=SourceContentType(str(payload["content_type"])),
            routing_policy_version=str(payload["routing_policy_version"]),
            analyzers=tuple(
                AnalyzerContract(
                    **{
                        key: value
                        for key, value in dict(item).items()
                        if key != "fingerprint"
                    }
                )
                for item in payload["analyzers"]
            ),
            window_chunks=int(payload["window_chunks"]),
            max_analyzer_calls=int(payload["max_analyzer_calls"]),
            mkaos_capability=str(payload["mkaos_capability"]),
            abstraction_policy_version=str(payload["abstraction_policy_version"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("frozen Source analysis strategy is invalid") from exc
    if not expected_fingerprint or strategy.fingerprint != expected_fingerprint:
        raise ValueError("frozen Source analysis strategy fingerprint drifted")
    return strategy


@dataclass(frozen=True, slots=True)
class AnalysisTask:
    stable_key: str
    analysis_plan_asset_version_id: str
    logical_document_scope_hash: str
    analyzer: AnalyzerContract
    scale: str
    range_start: int
    range_end: int
    label: str
    source_chunk_asset_version_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stable_key": self.stable_key,
            "analysis_plan_asset_version_id": self.analysis_plan_asset_version_id,
            "logical_document_scope_hash": self.logical_document_scope_hash,
            "analyzer": self.analyzer.to_dict(),
            "scale": self.scale,
            "range_start": self.range_start,
            "range_end": self.range_end,
            "label": self.label,
            "source_chunk_asset_version_ids": list(self.source_chunk_asset_version_ids),
        }


def _specs(skill_id: str, *dimensions: str) -> tuple[AnalyzerMethodologySpec, ...]:
    return tuple(
        AnalyzerMethodologySpec(dimension, skill_id, dimension.replace("_", " "))
        for dimension in dimensions
    )


_PROFILES = {
    SourceContentType.WEB_NOVEL: SourceAnalysisProfile(
        "web_novel_commercial",
        "2.0",
        SourceContentType.WEB_NOVEL,
        (
            *_specs(
                "hot-novel-deconstruction",
                "structure",
                "pacing",
                "conflict",
                "character_mechanism",
                "relationship_mechanism",
                "emotion_curve",
                "foreshadowing",
                "information_progression",
                "originality_copyright_risk",
            ),
            *_specs(
                "hot-novel-business-deconstruction",
                "hook",
                "reward_payoff",
                "reader_promise",
                "serialization",
                "commercial_logic",
            ),
        ),
        4,
        2_000,
        "mkaos.knowledge.extract",
        "anti-copy-abstraction.2.0",
    ),
    SourceContentType.PUBLISHED_FICTION: SourceAnalysisProfile(
        "published_fiction_craft",
        "2.0",
        SourceContentType.PUBLISHED_FICTION,
        _specs(
            "published-fiction-craft-analysis",
            "structure",
            "pacing",
            "scene_craft",
            "narrative_distance",
            "character_arc",
            "subtext",
            "transition",
            "emotion_curve",
            "originality_copyright_risk",
        ),
        5,
        1_200,
        "mkaos.template.extract",
        "published-fiction-abstraction.1.0",
    ),
    SourceContentType.CLASSIC_LITERATURE: SourceAnalysisProfile(
        "classic_literary_depth",
        "2.0",
        SourceContentType.CLASSIC_LITERATURE,
        _specs(
            "classic-literary-depth-analysis",
            "structure",
            "theme_system",
            "social_pressure",
            "symbol_function",
            "fate_curve",
            "moral_dilemma",
            "character_arc",
            "originality_copyright_risk",
        ),
        5,
        1_200,
        "mkaos.knowledge.extract",
        "classic-literature-abstraction.1.0",
    ),
    SourceContentType.WRITING_THEORY: SourceAnalysisProfile(
        "writing_theory_rules",
        "2.0",
        SourceContentType.WRITING_THEORY,
        _specs(
            "multidisciplinary-knowledge",
            "craft_principle",
            "concept_definition",
            "causal_constraints",
            "misuse_risk",
            "review_check",
            "originality_copyright_risk",
        ),
        6,
        800,
        "mkaos.rule.extract",
        "writing-theory-abstraction.2.0",
    ),
    SourceContentType.PROFESSIONAL_KNOWLEDGE: SourceAnalysisProfile(
        "professional_knowledge",
        "2.0",
        SourceContentType.PROFESSIONAL_KNOWLEDGE,
        _specs(
            "multidisciplinary-knowledge",
            "core_concept",
            "causal_constraints",
            "credibility_rule",
            "conflict_generator",
            "misuse_risk",
            "review_check",
            "originality_copyright_risk",
        ),
        8,
        600,
        "mkaos.knowledge.extract",
        "multidisciplinary-abstraction.2.0",
    ),
    SourceContentType.HISTORY_SOCIAL_SCIENCE: SourceAnalysisProfile(
        "history_social_science",
        "2.0",
        SourceContentType.HISTORY_SOCIAL_SCIENCE,
        _specs(
            "multidisciplinary-knowledge",
            "historical_causality",
            "institutional_constraint",
            "social_dynamics",
            "source_reliability",
            "misuse_risk",
        ),
        8,
        600,
        "mkaos.knowledge.extract",
        "multidisciplinary-abstraction.2.0",
    ),
    SourceContentType.BIOGRAPHY_MEMOIR: SourceAnalysisProfile(
        "biography_memoir",
        "2.0",
        SourceContentType.BIOGRAPHY_MEMOIR,
        (
            *_specs(
                "published-fiction-craft-analysis",
                "narrative_distance",
                "character_arc",
                "scene_craft",
            ),
            *_specs(
                "multidisciplinary-knowledge",
                "social_pressure",
                "source_reliability",
                "misuse_risk",
            ),
        ),
        6,
        900,
        "mkaos.knowledge.extract",
        "biography-abstraction.1.0",
    ),
    SourceContentType.PHILOSOPHY_ESSAY: SourceAnalysisProfile(
        "philosophy_essay",
        "2.0",
        SourceContentType.PHILOSOPHY_ESSAY,
        _specs(
            "multidisciplinary-knowledge",
            "argument_structure",
            "concept_definition",
            "assumption",
            "counterargument",
            "moral_dilemma",
            "misuse_risk",
        ),
        8,
        600,
        "mkaos.rule.extract",
        "philosophy-abstraction.1.0",
    ),
    SourceContentType.PLATFORM_RULES: SourceAnalysisProfile(
        "platform_rules",
        "2.0",
        SourceContentType.PLATFORM_RULES,
        _specs(
            "platform-strategy-os",
            "platform_policy",
            "eligibility_rule",
            "retention_constraint",
            "release_constraint",
            "compliance_risk",
        ),
        8,
        500,
        "mkaos.rule.extract",
        "platform-rule-abstraction.2.0",
    ),
}


def resolve_analysis_strategy(
    content_type: SourceContentType,
    *,
    registry: SourceMethodologyRegistry,
    routing_policy_version: str,
) -> ResolvedAnalysisStrategy:
    content_type = SourceContentType(content_type)
    try:
        profile = _PROFILES[content_type]
    except KeyError as exc:
        raise ValueError(
            f"Source content type is not routable: {content_type}"
        ) from exc
    capabilities = default_capability_registry()
    capabilities.resolve("deconstruction.observe")
    capabilities.resolve(profile.mkaos_capability)
    analyzers: list[AnalyzerContract] = []
    for spec in profile.methodology_specs:
        methodology = registry.require(spec.skill_id)
        analyzers.append(
            AnalyzerContract(
                analyzer_id=f"novel-forge.{profile.profile_id}.{spec.dimension}",
                analyzer_version=profile.profile_version,
                dimension=spec.dimension,
                schema_version="source-deconstruction-observation.v1",
                prompt_id=f"source.{profile.profile_id}.{spec.dimension}",
                prompt_version=profile.profile_version,
                skill_id=methodology.skill_id,
                skill_version=methodology.skill_version,
                capability_id="deconstruction.observe",
                capability_version="1.0",
                provider_policy_version="1.0",
                aggregation_policy_version="2.0",
                recommended_scales=("DOCUMENT_SECTION", "LOGICAL_DOCUMENT"),
                methodology_content_hash=methodology.content_digest,
            )
        )
    return ResolvedAnalysisStrategy(
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
        content_type=profile.content_type,
        routing_policy_version=routing_policy_version,
        analyzers=tuple(analyzers),
        window_chunks=profile.window_chunks,
        max_analyzer_calls=profile.max_analyzer_calls,
        mkaos_capability=profile.mkaos_capability,
        abstraction_policy_version=profile.abstraction_policy_version,
    )


def plan_analysis_tasks(
    *,
    strategy: ResolvedAnalysisStrategy,
    logical_document_scope: LogicalDocumentScope,
    analysis_plan_asset_version_id: str,
    chunks: Iterable[dict[str, Any]],
) -> tuple[AnalysisTask, ...]:
    if not analysis_plan_asset_version_id.strip():
        raise ValueError("analysis plan AssetVersion is required")
    ordered = tuple(sorted(chunks, key=lambda row: int(row["chunk_index"])))
    if tuple(str(item["asset_version_id"]) for item in ordered) != (
        logical_document_scope.source_chunk_asset_version_ids
    ):
        raise ValueError("analysis chunks differ from LogicalDocument scope")
    tasks: list[AnalysisTask] = []
    for window_start in range(0, len(ordered), strategy.window_chunks):
        window = ordered[window_start : window_start + strategy.window_chunks]
        start = window_start + 1
        end = window_start + len(window)
        for analyzer in strategy.analyzers:
            identity = {
                "analysis_plan_asset_version_id": analysis_plan_asset_version_id,
                "logical_document_scope_hash": logical_document_scope.scope_hash,
                "range": [start, end],
                "analyzer_contract_hash": analyzer.fingerprint,
                "source_chunk_asset_version_ids": [
                    str(item["asset_version_id"]) for item in window
                ],
            }
            tasks.append(
                AnalysisTask(
                    stable_key=canonical_hash(identity),
                    analysis_plan_asset_version_id=analysis_plan_asset_version_id,
                    logical_document_scope_hash=logical_document_scope.scope_hash,
                    analyzer=analyzer,
                    scale="DOCUMENT_SECTION",
                    range_start=start,
                    range_end=end,
                    label=f"logical document chunks {start}-{end}",
                    source_chunk_asset_version_ids=tuple(
                        str(item["asset_version_id"]) for item in window
                    ),
                )
            )
    if not tasks or len(tasks) > strategy.max_analyzer_calls:
        raise ValueError("analysis strategy budget exceeded or produced no tasks")
    return tuple(tasks)


__all__ = [
    "AnalysisTask",
    "AnalyzerMethodologySpec",
    "ResolvedAnalysisStrategy",
    "SourceAnalysisProfile",
    "analysis_strategy_from_dict",
    "plan_analysis_tasks",
    "resolve_analysis_strategy",
]
