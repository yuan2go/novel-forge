from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from novel_forge.modules.production_execution import default_capability_registry
from novel_forge.modules.source_authority.deconstruction import AnalyzerContract

from .methodologies import SourceMethodologyRegistry
from .profiling import LogicalDocumentScope, SourceContentType, canonical_hash
from .craft_discovery import WRITING_METHODS_ROUTING, craft_discovery_strategy


SOURCE_PROMPT_OVERHEAD_RESERVE_BYTES = 32_000


def derive_corpus_sample_byte_limit(
    *,
    model_context_limit: int,
    output_token_reserve: int,
    token_safety_margin: int,
    token_framing_overhead: int,
) -> int:
    limit = (
        model_context_limit
        - output_token_reserve
        - token_safety_margin
        - token_framing_overhead
        - SOURCE_PROMPT_OVERHEAD_RESERVE_BYTES
    )
    if limit <= 0:
        raise ValueError("Provider context leaves no bounded corpus sample budget")
    return limit


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
    execution_mode: str = "WINDOWED_SINGLE_DIMENSION"
    sampling_policy_version: str = "source-analysis-windowing.v2"
    sample_byte_limit: int = 0

    def __post_init__(self) -> None:
        if self.execution_mode not in {
            "WINDOWED_SINGLE_DIMENSION",
            "CORPUS_COMPOUND_SAMPLE",
        }:
            raise ValueError("Source analysis execution mode is invalid")
        if not self.sampling_policy_version.strip():
            raise ValueError("Source analysis sampling policy is required")
        if self.window_chunks <= 0 or self.max_analyzer_calls <= 0:
            raise ValueError("Source analysis bounds must be positive")
        if self.execution_mode == "CORPUS_COMPOUND_SAMPLE" and (
            self.sample_byte_limit <= 0
        ):
            raise ValueError("compound corpus analysis requires a sample byte limit")
        if self.execution_mode != "CORPUS_COMPOUND_SAMPLE" and (
            self.sample_byte_limit != 0
        ):
            raise ValueError("windowed Source analysis cannot claim a corpus byte limit")

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
            "execution_mode": self.execution_mode,
            "sampling_policy_version": self.sampling_policy_version,
            "sample_byte_limit": self.sample_byte_limit,
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
            execution_mode=str(
                payload.get("execution_mode") or "WINDOWED_SINGLE_DIMENSION"
            ),
            sampling_policy_version=str(
                payload.get("sampling_policy_version")
                or "source-analysis-windowing.v2"
            ),
            sample_byte_limit=int(payload.get("sample_byte_limit") or 0),
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
    compound_analyzers: tuple[AnalyzerContract, ...] = ()
    sampling_manifest: dict[str, Any] = field(default_factory=dict)

    @property
    def requested_analyzers(self) -> tuple[AnalyzerContract, ...]:
        return self.compound_analyzers or (self.analyzer,)

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
            "compound_analyzers": [
                item.to_dict() for item in self.compound_analyzers
            ],
            "sampling_manifest": dict(self.sampling_manifest),
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
    if routing_policy_version == WRITING_METHODS_ROUTING:
        if content_type != SourceContentType.WRITING_THEORY:
            raise ValueError("Writing methods require a governed writing-theory profile")
        profile = SourceAnalysisProfile(
            "writing_theory_methods", "1.0", content_type,
            _specs("multidisciplinary-knowledge", "craft_principle"),
            profile.window_chunks, profile.max_analyzer_calls,
            "mkaos.knowledge.extract", profile.abstraction_policy_version,
        )
        registry = SourceMethodologyRegistry(
            registry.skill_root,
            versions={**registry.versions, "multidisciplinary-knowledge": "1.2.0"},
        )
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
                schema_version="source-mechanism-observation.v2",
                prompt_id=f"source.{profile.profile_id}.{spec.dimension}",
                prompt_version="2.0",
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
    return craft_discovery_strategy(ResolvedAnalysisStrategy(
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
        content_type=profile.content_type,
        routing_policy_version=routing_policy_version,
        analyzers=tuple(analyzers),
        window_chunks=profile.window_chunks,
        max_analyzer_calls=profile.max_analyzer_calls,
        mkaos_capability=profile.mkaos_capability,
        abstraction_policy_version=profile.abstraction_policy_version,
    ))


_CORPUS_ANALYSIS_CONTRACTS: dict[
    str, tuple[str, str, tuple[tuple[str, str], ...], str]
] = {
    "LONG_NOVEL": (
        "classical_novel_craft",
        "published-fiction-craft-analysis",
        (
            ("structure", "multi-scale structure and conflict-unit progression"),
            ("conflict", "conflict escalation and reversal"),
            ("character_choice_cost", "character choice, consequence, and cost"),
            ("information_gap", "information asymmetry between actors and reader"),
            ("foreshadowing_payoff", "setup, delayed consequence, and payoff"),
            ("pacing", "rhythm across the sampled beginning, middle, and ending"),
            ("chapter_hook", "chapter ending pressure and forward question"),
        ),
        "mkaos.knowledge.extract",
    ),
    "SHORT_STORY_COLLECTION": (
        "classical_short_story_craft",
        "published-fiction-craft-analysis",
        (
            ("structure", "complete-story structure"),
            ("conflict", "conflict escalation and reversal"),
            ("character_choice_cost", "choice, consequence, and cost"),
            ("information_gap", "information asymmetry and reveal"),
            ("foreshadowing_payoff", "setup and payoff inside a complete story"),
            ("pacing", "compression and scene rhythm"),
            ("chapter_hook", "opening and closing narrative pressure"),
        ),
        "mkaos.knowledge.extract",
    ),
    "POETRY_COLLECTION": (
        "classical_poetry_craft",
        "classic-literary-depth-analysis",
        (
            ("imagery", "image system and sensory anchoring"),
            ("emotion_turn", "emotional transition rather than invented plot"),
            ("point_of_view", "speaker and narrative point of view"),
            ("rhythm", "line, cadence, repetition, and pause"),
            ("concise_expression", "compression and implication"),
            ("scene_atmosphere", "scene atmosphere and tonal construction"),
        ),
        "mkaos.knowledge.extract",
    ),
    "APHORISM_COLLECTION": (
        "classical_aphorism_reasoning",
        "multidisciplinary-knowledge",
        (
            ("concept_definition", "conceptual distinction"),
            ("value_conflict", "bounded value tension"),
            ("argument_structure", "implicit reasoning structure"),
            ("historical_context", "historically situated applicability"),
            ("misuse_risk", "risk of universalizing a literary judgment"),
        ),
        "mkaos.rule.extract",
    ),
    "PHILOSOPHY_CLASSIC": (
        "classical_philosophy_reasoning",
        "multidisciplinary-knowledge",
        (
            ("concept_definition", "conceptual distinction"),
            ("value_conflict", "value and duty conflict"),
            ("argument_structure", "argument and counter-position"),
            ("historical_context", "historically situated applicability"),
        ),
        "mkaos.rule.extract",
    ),
    "DIDACTIC_COLLECTION": (
        "classical_didactic_craft",
        "classic-literary-depth-analysis",
        (
            ("structure", "didactic sequence structure"),
            ("rhythm", "cadence, parallelism, and sonic pattern"),
            ("imagery", "image pairing and contrast"),
            ("concise_expression", "compression and mnemonic expression"),
            ("historical_context", "historically situated learning use"),
        ),
        "mkaos.rule.extract",
    ),
}


def resolve_corpus_analysis_strategy(
    content_type: SourceContentType,
    *,
    collection_kind: str,
    registry: SourceMethodologyRegistry,
    routing_policy_version: str,
    sample_byte_limit: int,
) -> ResolvedAnalysisStrategy:
    if routing_policy_version == WRITING_METHODS_ROUTING:
        raise ValueError("Writing methods require a writing-theory document profile")
    try:
        profile_id, skill_id, dimensions, mkaos_capability = (
            _CORPUS_ANALYSIS_CONTRACTS[collection_kind]
        )
    except KeyError as exc:
        raise ValueError(
            f"unsupported governed corpus collection kind: {collection_kind}"
        ) from exc
    methodology = registry.require(skill_id)
    capabilities = default_capability_registry()
    capabilities.resolve("deconstruction.observe")
    capabilities.resolve(mkaos_capability)
    analyzers = tuple(
        AnalyzerContract(
            analyzer_id=f"novel-forge.{profile_id}.{dimension}",
            analyzer_version="1.0",
            dimension=dimension,
            schema_version="source-deconstruction-observation.v1",
            prompt_id=f"source.{profile_id}.compound",
            prompt_version="1.0",
            skill_id=methodology.skill_id,
            skill_version=methodology.skill_version,
            capability_id="deconstruction.observe",
            capability_version="1.0",
            provider_policy_version="1.0",
            aggregation_policy_version="3.0",
            recommended_scales=("BOOK",),
            methodology_content_hash=methodology.content_digest,
        )
        for dimension, _focus in dimensions
    )
    return craft_discovery_strategy(ResolvedAnalysisStrategy(
        profile_id=profile_id,
        profile_version="1.1",
        content_type=SourceContentType(content_type),
        routing_policy_version=routing_policy_version,
        analyzers=analyzers,
        window_chunks=1,
        max_analyzer_calls=1,
        mkaos_capability=mkaos_capability,
        abstraction_policy_version="classical-corpus-anti-copy.1.0",
        execution_mode="CORPUS_COMPOUND_SAMPLE",
        sampling_policy_version="classical-corpus-stratified-sampling.v2",
        sample_byte_limit=sample_byte_limit,
    ))


def plan_analysis_tasks(
    *,
    strategy: ResolvedAnalysisStrategy,
    logical_document_scope: LogicalDocumentScope,
    analysis_plan_asset_version_id: str,
    chunks: Iterable[dict[str, Any]],
    source_units: Iterable[dict[str, Any]] = (),
    collection_kind: str = "",
) -> tuple[AnalysisTask, ...]:
    if not analysis_plan_asset_version_id.strip():
        raise ValueError("analysis plan AssetVersion is required")
    ordered = tuple(sorted(chunks, key=lambda row: int(row["chunk_index"])))
    if tuple(str(item["asset_version_id"]) for item in ordered) != (
        logical_document_scope.source_chunk_asset_version_ids
    ):
        raise ValueError("analysis chunks differ from LogicalDocument scope")
    if strategy.execution_mode == "CORPUS_COMPOUND_SAMPLE":
        return _plan_corpus_compound_task(
            strategy=strategy,
            logical_document_scope=logical_document_scope,
            analysis_plan_asset_version_id=analysis_plan_asset_version_id,
            chunks=ordered,
            source_units=tuple(source_units),
            collection_kind=collection_kind,
        )
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


def _plan_corpus_compound_task(
    *,
    strategy: ResolvedAnalysisStrategy,
    logical_document_scope: LogicalDocumentScope,
    analysis_plan_asset_version_id: str,
    chunks: tuple[dict[str, Any], ...],
    source_units: tuple[dict[str, Any], ...],
    collection_kind: str,
) -> tuple[AnalysisTask, ...]:
    if collection_kind not in _CORPUS_ANALYSIS_CONTRACTS or not source_units:
        raise ValueError("compound corpus analysis requires governed SourceUnit input")
    ordered_units = tuple(sorted(source_units, key=lambda row: int(row["ordinal"])))
    if any(str(item.get("status") or "") != "AVAILABLE" for item in ordered_units):
        raise ValueError("compound corpus analysis cannot sample unavailable SourceUnits")

    def unit_chunks(unit: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        start = int(unit["normalized_byte_start"])
        end = int(unit["normalized_byte_end"])
        return tuple(
            chunk
            for chunk in chunks
            if int(chunk["source_byte_start"]) < end
            and int(chunk["source_byte_end"]) > start
        )

    sampled: list[dict[str, Any]] = []
    if collection_kind == "LONG_NOVEL":
        window_width = min(2, len(chunks))
        middle_start = max(0, (len(chunks) - window_width) // 2)
        for role, window in (
            ("OPENING_CONTINUOUS_WINDOW", chunks[:window_width]),
            (
                "MIDDLE_CONTINUOUS_WINDOW",
                chunks[middle_start : middle_start + window_width],
            ),
            ("ENDING_CONTINUOUS_WINDOW", chunks[-window_width:]),
        ):
            sampled.append(
                {
                    "role": role,
                    "complete_unit": False,
                    "source_unit_ordinals": [],
                    "source_chunk_asset_version_ids": [
                        str(item["asset_version_id"]) for item in window
                    ],
                }
            )
        chapter_units = tuple(
            item for item in ordered_units if str(item.get("kind")) == "CHAPTER"
        ) or ordered_units
        conflict_unit = chapter_units[max(0, (len(chapter_units) - 1) // 3)]
        conflict_chunks = unit_chunks(conflict_unit)
        if not conflict_chunks:
            raise ValueError("complete conflict-unit sample has no SourceChunk")
        sampled.append(
            {
                "role": "COMPLETE_CONFLICT_UNIT",
                "complete_unit": True,
                "source_unit_ordinals": [int(conflict_unit["ordinal"])],
                "source_chunk_asset_version_ids": [
                    str(item["asset_version_id"]) for item in conflict_chunks
                ],
            }
        )
    else:
        target_count = {
            "SHORT_STORY_COLLECTION": 3,
            "POETRY_COLLECTION": 8,
            "APHORISM_COLLECTION": 8,
            "PHILOSOPHY_CLASSIC": 12,
            "DIDACTIC_COLLECTION": 6,
        }[collection_kind]
        indexes = _stratified_indexes(len(ordered_units), target_count)
        role = (
            "COMPLETE_STORY"
            if collection_kind == "SHORT_STORY_COLLECTION"
            else "COMPLETE_PIECE"
        )
        candidates: list[tuple[int, dict[str, Any], int]] = []
        chunk_bytes = {
            str(item["asset_version_id"]): int(item["byte_size"]) for item in chunks
        }
        for position, index in enumerate(indexes, start=1):
            unit = ordered_units[index]
            selected_chunks = unit_chunks(unit)
            if not selected_chunks:
                raise ValueError("complete SourceUnit sample has no SourceChunk")
            sample = {
                "role": f"{role}_{position}",
                "complete_unit": True,
                "source_unit_ordinals": [int(unit["ordinal"])],
                "source_chunk_asset_version_ids": [
                    str(item["asset_version_id"]) for item in selected_chunks
                ],
            }
            candidates.append(
                (
                    position,
                    sample,
                    sum(
                        chunk_bytes[chunk_id]
                        for chunk_id in sample["source_chunk_asset_version_ids"]
                    ),
                )
            )
        selected_ids: set[str] = set()
        for _position, sample, _sample_bytes in sorted(
            candidates, key=lambda item: (item[2], item[0])
        ):
            candidate_ids = set(sample["source_chunk_asset_version_ids"])
            total = sum(chunk_bytes[item] for item in selected_ids | candidate_ids)
            if total <= strategy.sample_byte_limit:
                sampled.append(sample)
                selected_ids.update(candidate_ids)
        if not sampled:
            raise ValueError(
                "complete SourceUnit exceeds the frozen corpus sample byte limit"
            )
        sampled.sort(key=lambda item: int(str(item["role"]).rsplit("_", 1)[1]))
    selected_ids = {
        chunk_id
        for sample in sampled
        for chunk_id in sample["source_chunk_asset_version_ids"]
    }
    selected_chunks = tuple(
        item for item in chunks if str(item["asset_version_id"]) in selected_ids
    )
    if not selected_chunks:
        raise ValueError("compound corpus sampling produced no SourceChunk evidence")
    sampled_byte_count = sum(int(item["byte_size"]) for item in selected_chunks)
    if sampled_byte_count > strategy.sample_byte_limit:
        raise ValueError("compound corpus sample exceeds its frozen byte limit")
    _, _, dimension_specs, _ = _CORPUS_ANALYSIS_CONTRACTS[collection_kind]
    whole_work_analyzed = len(selected_chunks) == len(chunks)
    sampling_manifest = {
        "schema_version": "classical-corpus-analysis-sample.v1",
        "sampling_policy_version": strategy.sampling_policy_version,
        "collection_kind": collection_kind,
        "source_unit_count": len(ordered_units),
        "sampled_source_unit_ordinals": sorted(
            {
                ordinal
                for sample in sampled
                for ordinal in sample["source_unit_ordinals"]
            }
        ),
        "sampled_chunk_count": len(selected_chunks),
        "sampled_byte_count": sampled_byte_count,
        "sample_byte_limit": strategy.sample_byte_limit,
        "whole_work_analyzed": whole_work_analyzed,
        "uncovered_chunk_count": len(chunks) - len(selected_chunks),
        "samples": sampled,
        "dimension_guidance": {
            dimension: focus for dimension, focus in dimension_specs
        },
        "coverage_claim": (
            "FULL_WORK" if whole_work_analyzed else "BOUNDED_STRATIFIED_SAMPLE"
        ),
    }
    identity = {
        "analysis_plan_asset_version_id": analysis_plan_asset_version_id,
        "logical_document_scope_hash": logical_document_scope.scope_hash,
        "analyzer_contract_hashes": [
            item.fingerprint for item in strategy.analyzers
        ],
        "source_chunk_asset_version_ids": [
            str(item["asset_version_id"]) for item in selected_chunks
        ],
        "sampling_manifest": sampling_manifest,
    }
    task = AnalysisTask(
        stable_key=canonical_hash(identity),
        analysis_plan_asset_version_id=analysis_plan_asset_version_id,
        logical_document_scope_hash=logical_document_scope.scope_hash,
        analyzer=strategy.analyzers[0],
        scale="BOOK",
        range_start=int(selected_chunks[0]["chunk_index"]) + 1,
        range_end=int(selected_chunks[-1]["chunk_index"]) + 1,
        label=(
            f"{collection_kind} bounded stratified sample; "
            f"{len(selected_chunks)}/{len(chunks)} chunks"
        ),
        source_chunk_asset_version_ids=tuple(
            str(item["asset_version_id"]) for item in selected_chunks
        ),
        compound_analyzers=strategy.analyzers,
        sampling_manifest=sampling_manifest,
    )
    return (task,)


def _stratified_indexes(size: int, target_count: int) -> tuple[int, ...]:
    if size <= 0 or target_count <= 0:
        raise ValueError("stratified sampling bounds must be positive")
    if size <= target_count:
        return tuple(range(size))
    return tuple(
        sorted(
            {
                round(index * (size - 1) / (target_count - 1))
                for index in range(target_count)
            }
        )
    )


__all__ = [
    "AnalysisTask",
    "AnalyzerMethodologySpec",
    "ResolvedAnalysisStrategy",
    "SourceAnalysisProfile",
    "analysis_strategy_from_dict",
    "derive_corpus_sample_byte_limit",
    "plan_analysis_tasks",
    "resolve_analysis_strategy",
    "resolve_corpus_analysis_strategy",
    "SOURCE_PROMPT_OVERHEAD_RESERVE_BYTES",
]
