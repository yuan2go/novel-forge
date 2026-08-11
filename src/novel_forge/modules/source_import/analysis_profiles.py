"""Versioned, budgeted analyzer selection for imported Source types."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from novel_forge.modules.source_authority.deconstruction import AnalyzerContract

from .artifacts import source_skill_version


_WEB_NOVEL_DIMENSIONS = (
    "structure",
    "pacing",
    "hook",
    "reward_payoff",
    "reader_promise",
    "conflict",
    "character_mechanism",
    "relationship_mechanism",
    "emotion_curve",
    "foreshadowing",
    "information_progression",
    "serialization",
    "commercial_logic",
    "originality_copyright_risk",
)


@dataclass(frozen=True, slots=True)
class SourceAnalysisProfile:
    profile_id: str
    profile_version: str
    dimensions: tuple[str, ...]
    window_chunks: int
    max_analyzer_calls: int
    mkaos_capability: str
    abstraction_policy_version: str
    analysis_skill_id: str


@dataclass(frozen=True, slots=True)
class AnalysisTask:
    stable_key: str
    analyzer: AnalyzerContract
    scale: str
    range_start: int
    range_end: int
    label: str
    source_chunk_asset_version_ids: tuple[str, ...]
    profile_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "stable_key": self.stable_key,
            "analyzer": self.analyzer.to_dict(),
            "scale": self.scale,
            "range_start": self.range_start,
            "range_end": self.range_end,
            "label": self.label,
            "source_chunk_asset_version_ids": list(
                self.source_chunk_asset_version_ids
            ),
            "profile_id": self.profile_id,
        }


_PROFILES = {
    # AUTO is a routing policy, not an analyzer profile. Its dimensions are the
    # conservative upper bound used by import preview cost estimation.
    "auto": SourceAnalysisProfile(
        profile_id="auto",
        profile_version="1.0",
        dimensions=_WEB_NOVEL_DIMENSIONS,
        window_chunks=4,
        max_analyzer_calls=2_000,
        mkaos_capability="mkaos.knowledge.extract",
        abstraction_policy_version="auto-routing.1.0",
        analysis_skill_id="source-content-profiling",
    ),
    "web_novel": SourceAnalysisProfile(
        profile_id="web_novel",
        profile_version="1.0",
        dimensions=_WEB_NOVEL_DIMENSIONS,
        window_chunks=4,
        max_analyzer_calls=2_000,
        mkaos_capability="mkaos.knowledge.extract",
        abstraction_policy_version="anti-copy-abstraction.1.0",
        analysis_skill_id="hot-novel-deconstruction",
    ),
    "published_fiction": SourceAnalysisProfile(
        profile_id="published_fiction",
        profile_version="1.0",
        dimensions=(
            "structure",
            "conflict",
            "character_mechanism",
            "relationship_mechanism",
            "emotion_curve",
            "information_progression",
            "foreshadowing",
            "originality_copyright_risk",
        ),
        window_chunks=6,
        max_analyzer_calls=1_200,
        mkaos_capability="mkaos.knowledge.extract",
        abstraction_policy_version="published-fiction-abstraction.1.0",
        analysis_skill_id="published-fiction-craft-analysis",
    ),
    "classic_literature": SourceAnalysisProfile(
        profile_id="classic_literature",
        profile_version="1.0",
        dimensions=(
            "structure",
            "conflict",
            "character_mechanism",
            "relationship_mechanism",
            "emotion_curve",
            "information_progression",
            "foreshadowing",
            "originality_copyright_risk",
        ),
        window_chunks=8,
        max_analyzer_calls=1_000,
        mkaos_capability="mkaos.knowledge.extract",
        abstraction_policy_version="classic-literature-abstraction.1.0",
        analysis_skill_id="classic-literary-depth-analysis",
    ),
    "writing_theory": SourceAnalysisProfile(
        profile_id="writing_theory",
        profile_version="1.0",
        dimensions=(
            "structure",
            "pacing",
            "conflict",
            "character_mechanism",
            "information_progression",
            "originality_copyright_risk",
        ),
        window_chunks=6,
        max_analyzer_calls=800,
        mkaos_capability="mkaos.rule.extract",
        abstraction_policy_version="writing-theory-abstraction.1.0",
        analysis_skill_id="multidisciplinary-knowledge",
    ),
    "platform_rules": SourceAnalysisProfile(
        profile_id="platform_rules",
        profile_version="1.0",
        dimensions=(
            "reader_promise",
            "serialization",
            "commercial_logic",
            "originality_copyright_risk",
        ),
        window_chunks=8,
        max_analyzer_calls=400,
        mkaos_capability="mkaos.rule.extract",
        abstraction_policy_version="platform-rule-abstraction.1.0",
        analysis_skill_id="platform-strategy-os",
    ),
    "professional_knowledge": SourceAnalysisProfile(
        profile_id="professional_knowledge",
        profile_version="1.0",
        dimensions=(
            "structure",
            "conflict",
            "information_progression",
            "originality_copyright_risk",
        ),
        window_chunks=8,
        max_analyzer_calls=600,
        mkaos_capability="mkaos.knowledge.extract",
        abstraction_policy_version="multidisciplinary-abstraction.1.0",
        analysis_skill_id="multidisciplinary-knowledge",
    ),
}


def analysis_profile(profile_id: str) -> SourceAnalysisProfile:
    try:
        return _PROFILES[profile_id.strip().lower()]
    except KeyError as exc:
        raise ValueError(f"unsupported Source analysis profile: {profile_id}") from exc


def plan_analysis_tasks(
    *,
    profile_id: str,
    source_document_id: str,
    chunks: Iterable[dict[str, Any]],
) -> tuple[AnalysisTask, ...]:
    profile = analysis_profile(profile_id)
    if profile.profile_id == "auto":
        raise ValueError("AUTO Source profile must be resolved before analysis planning")
    ordered = tuple(sorted(chunks, key=lambda row: int(row["chunk_index"])))
    tasks: list[AnalysisTask] = []
    for window_start in range(0, len(ordered), profile.window_chunks):
        window = ordered[window_start : window_start + profile.window_chunks]
        start = window_start + 1
        end = window_start + len(window)
        for dimension in profile.dimensions:
            skill_id = profile.analysis_skill_id
            analyzer = AnalyzerContract(
                analyzer_id=f"novel-forge.{profile.profile_id}.{dimension}",
                analyzer_version="1.0",
                dimension=dimension,
                schema_version=(
                    f"source-{profile.profile_id.replace('_', '-')}-"
                    f"{dimension.replace('_', '-')}.v1"
                ),
                prompt_id=f"source.{profile.profile_id}.{dimension}",
                prompt_version="1.0",
                skill_id=skill_id,
                skill_version=source_skill_version(skill_id),
                capability_id="deconstruction.observe",
                capability_version="1.0",
                provider_policy_version="1.0",
                aggregation_policy_version="1.0",
                recommended_scales=("CHAPTER_WINDOW", "BOOK"),
            )
            tasks.append(
                AnalysisTask(
                    stable_key=(
                        f"{source_document_id}:{profile.profile_id}:{start}-{end}:"
                        f"{analyzer.analyzer_id}:{analyzer.fingerprint}"
                    ),
                    analyzer=analyzer,
                    scale="CHAPTER_WINDOW",
                    range_start=start,
                    range_end=end,
                    label=f"{profile.profile_id} chunks {start}-{end}",
                    source_chunk_asset_version_ids=tuple(
                        str(item["asset_version_id"]) for item in window
                    ),
                    profile_id=profile.profile_id,
                )
            )
    if len(tasks) > profile.max_analyzer_calls:
        raise ValueError(
            "analysis profile budget exceeded; split the import or raise a governed policy"
        )
    return tuple(tasks)


__all__ = [
    "AnalysisTask",
    "SourceAnalysisProfile",
    "analysis_profile",
    "plan_analysis_tasks",
]
