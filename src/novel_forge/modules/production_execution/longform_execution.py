from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping

from novel_forge.modules.production_execution.domain_execution import (
    CandidateKind,
    DomainExecutionCandidate,
    DomainExecutionPort,
    execute_domain_candidate,
)


class LongformAnalysisKind(StrEnum):
    RECAP = "recap"
    PLAN_VS_ACTUAL = "plan_vs_actual"
    DRIFT = "drift"
    ARC_CLOSURE = "arc_closure"
    ENDING_REACHABILITY = "ending_reachability"
    PLAN_CHANGE = "plan_change"
    CHARACTER_RELATIONSHIP_EXTRACTION = "character_relationship_extraction"
    LONG_RANGE_FORECAST = "long_range_forecast"


_CAPABILITY_BY_KIND = {
    LongformAnalysisKind.RECAP: "longform.recap.analyze",
    LongformAnalysisKind.PLAN_VS_ACTUAL: "longform.plan_vs_actual.judge",
    LongformAnalysisKind.DRIFT: "longform.plan_vs_actual.judge",
    LongformAnalysisKind.ARC_CLOSURE: "longform.arc_closure.judge",
    LongformAnalysisKind.ENDING_REACHABILITY: "longform.arc_closure.judge",
    LongformAnalysisKind.PLAN_CHANGE: "longform.plan_change.generate",
    LongformAnalysisKind.CHARACTER_RELATIONSHIP_EXTRACTION: "longform.recap.analyze",
    LongformAnalysisKind.LONG_RANGE_FORECAST: "longform.plan_change.generate",
}


def execute_longform_analysis(
    kind: LongformAnalysisKind | str,
    *,
    prompt: str,
    context: Mapping[str, Any],
    execution_port: DomainExecutionPort,
) -> DomainExecutionCandidate:
    normalized = LongformAnalysisKind(kind)
    candidate_kind = (
        CandidateKind.PLAN_CHANGE
        if normalized
        in {LongformAnalysisKind.PLAN_CHANGE, LongformAnalysisKind.LONG_RANGE_FORECAST}
        else CandidateKind.JUDGE
        if normalized
        in {
            LongformAnalysisKind.PLAN_VS_ACTUAL,
            LongformAnalysisKind.DRIFT,
            LongformAnalysisKind.ARC_CLOSURE,
            LongformAnalysisKind.ENDING_REACHABILITY,
        }
        else CandidateKind.RAW_STRUCTURED_OUTPUT
    )
    operation = "generate" if candidate_kind is CandidateKind.PLAN_CHANGE else "analyze"
    return execute_domain_candidate(
        capability=_CAPABILITY_BY_KIND[normalized],
        operation=operation,
        candidate_kind=candidate_kind,
        prompt=prompt,
        context=context,
        execution_port=execution_port,
    )


__all__ = ["LongformAnalysisKind", "execute_longform_analysis"]
