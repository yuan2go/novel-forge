from typing import TYPE_CHECKING, Any

from .application import PostgresHierarchicalPlanningAuthority
from .definitions import (
    PLAN_BINDING_DEFINITION_VERSION,
    PLAN_BINDING_HANDLER_KEY,
    plan_binding_definitions,
)
from .domain import (
    CHAPTER_EXECUTION_STATE_KINDS,
    PLAN_HORIZON,
    PLAN_REALIZATION,
    READER_DISCLOSURE_STATUS,
    REALIZATION_AUTHORITY_ROLE_TYPES,
    CommitmentLevel,
    PlanContractType,
    PlanExecutionScope,
    PlanningHorizon,
    PlanningContract,
    RealizationLevel,
    validate_chapter_function_matrix,
    validate_planning_contract,
)
from .realization_domain import (
    NARRATIVE_REALIZATION_PROOF_SCHEMA_VERSION,
    NARRATIVE_REALIZATION_SCHEMA_VERSION,
    AcceptedBoundaryBinding,
    ArcPlanBinding,
    NarrativeRealizationContract,
    NarrativeRealizationCoverage,
    NarrativeRealizationEvent,
    NarrativeRealizationLifecycle,
    NarrativeRealizationProof,
    PlannedStateDelta,
    realization_hash,
    validate_narrative_realization_event_chain,
)

if TYPE_CHECKING:
    from .realization_application import (
        NarrativeRealizationCommand,
        PostgresNarrativeRealizationApplication,
    )


def __getattr__(name: str) -> Any:
    # WHY: Narrative Realization persistence imports its domain through this
    # package.  Load the PostgreSQL application only on demand so the package
    # remains acyclic for Book Authority and migration tooling.
    if name in {
        "NarrativeRealizationCommand",
        "PostgresNarrativeRealizationApplication",
    }:
        from .realization_application import (
            NarrativeRealizationCommand,
            PostgresNarrativeRealizationApplication,
        )

        return {
            "NarrativeRealizationCommand": NarrativeRealizationCommand,
            "PostgresNarrativeRealizationApplication": (
                PostgresNarrativeRealizationApplication
            ),
        }[name]
    raise AttributeError(name)

__all__ = [
    "CHAPTER_EXECUTION_STATE_KINDS",
    "CommitmentLevel",
    "PLAN_HORIZON",
    "PLAN_REALIZATION",
    "READER_DISCLOSURE_STATUS",
    "REALIZATION_AUTHORITY_ROLE_TYPES",
    "PlanContractType",
    "PlanExecutionScope",
    "PlanningHorizon",
    "PLAN_BINDING_DEFINITION_VERSION",
    "PLAN_BINDING_HANDLER_KEY",
    "PlanningContract",
    "RealizationLevel",
    "PostgresHierarchicalPlanningAuthority",
    "NarrativeRealizationCommand",
    "PostgresNarrativeRealizationApplication",
    "plan_binding_definitions",
    "validate_chapter_function_matrix",
    "validate_planning_contract",
    "AcceptedBoundaryBinding",
    "ArcPlanBinding",
    "NARRATIVE_REALIZATION_PROOF_SCHEMA_VERSION",
    "NARRATIVE_REALIZATION_SCHEMA_VERSION",
    "NarrativeRealizationContract",
    "NarrativeRealizationCoverage",
    "NarrativeRealizationEvent",
    "NarrativeRealizationLifecycle",
    "NarrativeRealizationProof",
    "PlannedStateDelta",
    "realization_hash",
    "validate_narrative_realization_event_chain",
]
