from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError

NARRATIVE_REALIZATION_SCHEMA_VERSION = "narrative-realization-contract.v1"
NARRATIVE_REALIZATION_PROOF_SCHEMA_VERSION = "narrative-realization-proof.v1"


def realization_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _json_value(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def _required(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise KernelError("NARRATIVE_REALIZATION_INVALID", f"{field} is required")
    return normalized


def _hash(value: Any, field: str) -> str:
    normalized = _required(value, field)
    if len(normalized) != 71 or not normalized.startswith("sha256:"):
        raise KernelError(
            "NARRATIVE_REALIZATION_INVALID", f"{field} must be SHA-256 bound"
        )
    return normalized


def _strings(value: Any, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise KernelError("NARRATIVE_REALIZATION_INVALID", f"{field} must be an array")
    result = tuple(_required(item, f"{field}[]") for item in value)
    if len(set(result)) != len(result):
        raise KernelError(
            "NARRATIVE_REALIZATION_INVALID", f"{field} must contain unique values"
        )
    return result


class NarrativeRealizationLifecycle(StrEnum):
    PROPOSED = "PROPOSED"
    QUALIFIED = "QUALIFIED"
    ADMITTED = "ADMITTED"
    APPROVED = "APPROVED"
    FROZEN = "FROZEN"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


class NarrativeRealizationCoverage(StrEnum):
    PLANNED = "PLANNED"
    OBSERVED = "OBSERVED"
    ACCEPTED = "ACCEPTED"
    DEVIATED = "DEVIATED"
    NOT_OBSERVED = "NOT_OBSERVED"


@dataclass(frozen=True, slots=True)
class AcceptedBoundaryBinding:
    accepted_through_chapter: int
    story_state_version_id: str
    story_state_content_hash: str
    canon_version_id: str
    canon_content_hash: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AcceptedBoundaryBinding":
        if set(value) != {
            "accepted_through_chapter",
            "story_state_version_id",
            "story_state_content_hash",
            "canon_version_id",
            "canon_content_hash",
        }:
            raise KernelError(
                "NARRATIVE_REALIZATION_INVALID",
                "Accepted Boundary fields must match the contract exactly",
            )
        chapter = value.get("accepted_through_chapter")
        if not isinstance(chapter, int) or isinstance(chapter, bool) or chapter < 0:
            raise KernelError(
                "NARRATIVE_REALIZATION_INVALID",
                "accepted_through_chapter must be a non-negative integer",
            )
        result = cls(
            accepted_through_chapter=chapter,
            story_state_version_id=_required(
                value.get("story_state_version_id"), "story_state_version_id"
            ),
            story_state_content_hash=_hash(
                value.get("story_state_content_hash"), "story_state_content_hash"
            ),
            canon_version_id=_required(
                value.get("canon_version_id"), "canon_version_id"
            ),
            canon_content_hash=_hash(
                value.get("canon_content_hash"), "canon_content_hash"
            ),
        )
        return result


@dataclass(frozen=True, slots=True)
class ArcPlanBinding:
    arc_id: str
    asset_version_id: str
    content_hash: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ArcPlanBinding":
        if set(value) != {"arc_id", "asset_version_id", "content_hash"}:
            raise KernelError(
                "NARRATIVE_REALIZATION_INVALID",
                "Arc binding fields must match the contract exactly",
            )
        result = cls(
            arc_id=_required(value.get("arc_id"), "arc_id"),
            asset_version_id=_required(
                value.get("asset_version_id"), "arc asset_version_id"
            ),
            content_hash=_hash(value.get("content_hash"), "arc content_hash"),
        )
        return result


@dataclass(frozen=True, slots=True)
class PlannedStateDelta:
    state_kind: str
    entity_id: str
    from_state: str
    to_state: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PlannedStateDelta":
        if set(value) != {"state_kind", "entity_id", "from_state", "to_state"}:
            raise KernelError(
                "NARRATIVE_REALIZATION_INVALID",
                "planned state delta fields must match the contract exactly",
            )
        return cls(
            state_kind=_required(value.get("state_kind"), "state_kind"),
            entity_id=_required(value.get("entity_id"), "entity_id"),
            from_state=_required(value.get("from_state"), "from_state"),
            to_state=_required(value.get("to_state"), "to_state"),
        )


@dataclass(frozen=True, slots=True)
class KnowledgeBoundary:
    actor_knows: tuple[str, ...]
    reader_may_learn: tuple[str, ...]
    forbidden_disclosures: tuple[str, ...]

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any], *, work_requirements: bool = False
    ) -> "KnowledgeBoundary":
        if set(value) != {
            "actor_knows",
            "reader_may_learn",
            "forbidden_disclosures",
        }:
            raise KernelError(
                "NARRATIVE_REALIZATION_INVALID",
                "knowledge boundary fields must match the contract exactly",
            )
        result = cls(
            actor_knows=_strings(
                value.get("actor_knows"), "actor_knows", allow_empty=work_requirements
            ),
            reader_may_learn=_strings(
                value.get("reader_may_learn"),
                "reader_may_learn",
                allow_empty=work_requirements,
            ),
            forbidden_disclosures=_strings(
                value.get("forbidden_disclosures"),
                "forbidden_disclosures",
                allow_empty=work_requirements,
            ),
        )
        if set(result.reader_may_learn) & set(result.forbidden_disclosures):
            raise KernelError(
                "REALIZATION_KNOWLEDGE_BOUNDARY_INVALID",
                "a disclosure cannot be both permitted and forbidden",
            )
        return result


@dataclass(frozen=True, slots=True)
class NarrativeRealizationEvent:
    event_id: str
    slice_id: str
    chapter_number: int
    causes: tuple[str, ...]
    actor_ref: str
    motivation: str
    preconditions: tuple[str, ...]
    knowledge_boundary: KnowledgeBoundary
    action: str
    decision: str | None
    resistance: str | None
    consequence: str
    state_deltas: tuple[PlannedStateDelta, ...]
    disclosures: tuple[str, ...]
    obligation_actions: tuple[str, ...]
    arc_contributions: tuple[str, ...]
    irreversible_change: str | None
    next_event_ids: tuple[str, ...]
    required: bool
    feature_status: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any], *, work_requirements: bool = False
    ) -> "NarrativeRealizationEvent":
        allowed = {
            "event_id",
            "slice_id",
            "chapter_number",
            "causes",
            "actor_ref",
            "motivation",
            "preconditions",
            "knowledge_boundary",
            "action",
            "decision",
            "resistance",
            "consequence",
            "state_deltas",
            "disclosures",
            "obligation_actions",
            "arc_contributions",
            "irreversible_change",
            "next_event_ids",
            "required",
        }
        if work_requirements:
            allowed.add("feature_status")
        if set(value) != allowed:
            raise KernelError(
                "NARRATIVE_REALIZATION_INVALID",
                "realization event fields must match the contract exactly",
            )
        chapter = value.get("chapter_number")
        if not isinstance(chapter, int) or isinstance(chapter, bool) or chapter <= 0:
            raise KernelError(
                "REALIZATION_SLICE_INVALID", "event chapter_number must be positive"
            )
        boundary = value.get("knowledge_boundary")
        deltas = value.get("state_deltas")
        if (
            not isinstance(boundary, Mapping)
            or not isinstance(deltas, list)
            or (not deltas and not work_requirements)
        ):
            raise KernelError(
                "NARRATIVE_REALIZATION_INVALID",
                "event knowledge boundary and state deltas are required",
            )
        if not isinstance(value.get("required"), bool):
            raise KernelError(
                "NARRATIVE_REALIZATION_INVALID", "event required must be boolean"
            )
        features = value.get("feature_status", {})
        if work_requirements:
            if not isinstance(features, Mapping) or set(features) != {
                "decision",
                "resistance",
                "irreversible_change",
            }:
                raise KernelError(
                    "REALIZATION_FEATURE_STATUS_REQUIRED",
                    "Optional event features need exact applicability decisions",
                )
            for name, status in features.items():
                if (
                    not isinstance(status, Mapping)
                    or set(status) != {"status", "rationale"}
                    or status.get("status")
                    not in {"APPLICABLE", "NOT_APPLICABLE", "PROHIBITED"}
                    or not isinstance(status.get("rationale"), str)
                    or not status["rationale"].strip()
                    or (value[name] is None) != (status["status"] != "APPLICABLE")
                ):
                    raise KernelError(
                        "REALIZATION_FEATURE_STATUS_INVALID",
                        "An optional feature must agree with its explicit resolved applicability",
                    )
            if any(item.get("from_state") == item.get("to_state") for item in deltas):
                raise KernelError(
                    "REALIZATION_STATE_DELTA_NOOP",
                    "Confirmed zero change is an empty collection, not a fabricated no-op delta",
                )
        result = cls(
            event_id=_required(value.get("event_id"), "event_id"),
            slice_id=_required(value.get("slice_id"), "slice_id"),
            chapter_number=chapter,
            causes=_strings(value.get("causes"), "causes", allow_empty=True),
            actor_ref=_required(value.get("actor_ref"), "actor_ref"),
            motivation=_required(value.get("motivation"), "motivation"),
            preconditions=_strings(
                value.get("preconditions"),
                "preconditions",
                allow_empty=work_requirements,
            ),
            knowledge_boundary=KnowledgeBoundary.from_mapping(
                boundary, work_requirements=work_requirements
            ),
            action=_required(value.get("action"), "action"),
            decision=(
                None
                if work_requirements and value["decision"] is None
                else _required(value.get("decision"), "decision")
            ),
            resistance=(
                None
                if work_requirements and value["resistance"] is None
                else _required(value.get("resistance"), "resistance")
            ),
            consequence=_required(value.get("consequence"), "consequence"),
            state_deltas=tuple(PlannedStateDelta.from_mapping(item) for item in deltas),
            disclosures=_strings(
                value.get("disclosures"), "disclosures", allow_empty=work_requirements
            ),
            obligation_actions=_strings(
                value.get("obligation_actions"),
                "obligation_actions",
                allow_empty=work_requirements,
            ),
            arc_contributions=_strings(
                value.get("arc_contributions"),
                "arc_contributions",
                allow_empty=work_requirements,
            ),
            irreversible_change=(
                None
                if work_requirements and value["irreversible_change"] is None
                else _required(value.get("irreversible_change"), "irreversible_change")
            ),
            next_event_ids=_strings(
                value.get("next_event_ids"), "next_event_ids", allow_empty=True
            ),
            required=bool(value["required"]),
            feature_status={name: dict(status) for name, status in features.items()},
        )
        disclosures = set(result.disclosures)
        if not disclosures.issubset(set(result.knowledge_boundary.reader_may_learn)):
            raise KernelError(
                "REALIZATION_KNOWLEDGE_BOUNDARY_INVALID",
                "planned disclosures must be explicitly permitted for the reader",
            )
        if disclosures & set(result.knowledge_boundary.forbidden_disclosures):
            raise KernelError(
                "REALIZATION_KNOWLEDGE_BOUNDARY_INVALID",
                "planned disclosures intersect the frozen forbidden boundary",
            )
        return result

    def to_dict(self) -> dict[str, Any]:
        value = _json_value(asdict(self))
        if not self.feature_status:
            value.pop("feature_status")
        return value


@dataclass(frozen=True, slots=True)
class NarrativeRealizationProof:
    covered_event_ids: tuple[str, ...]
    covered_parent_objectives: tuple[str, ...]
    canon_state_legal: bool
    character_motivation_legal: bool
    world_rules_legal: bool
    knowledge_boundaries_legal: bool
    causal_escalation_proven: bool
    state_transitions_covered: bool
    obligations_covered: bool
    arc_contributions_covered: bool
    narrative_load_legal: bool
    chapter_decomposition_legal: bool
    semantic_evaluation_asset_version_id: str
    semantic_evaluation_hash: str
    schema_version: str = NARRATIVE_REALIZATION_PROOF_SCHEMA_VERSION
    design_admission: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "NarrativeRealizationProof":
        expected = {
            "schema_version",
            "covered_event_ids",
            "covered_parent_objectives",
            "canon_state_legal",
            "character_motivation_legal",
            "world_rules_legal",
            "knowledge_boundaries_legal",
            "causal_escalation_proven",
            "state_transitions_covered",
            "obligations_covered",
            "arc_contributions_covered",
            "narrative_load_legal",
            "chapter_decomposition_legal",
            "semantic_evaluation_asset_version_id",
            "semantic_evaluation_hash",
        }
        work_requirements = (
            value.get("schema_version") in {"narrative-realization-proof.v2", "narrative-realization-proof.v3"}
        )
        if work_requirements:
            expected.remove("causal_escalation_proven")
            expected.add("causal_alignment_proven")
            expected.add("design_admission")
        if set(value) != expected or value.get("schema_version") not in {
            NARRATIVE_REALIZATION_PROOF_SCHEMA_VERSION,
            "narrative-realization-proof.v2",
            "narrative-realization-proof.v3",
        }:
            raise KernelError(
                "NARRATIVE_REALIZATION_INVALID",
                "realization proof fields/schema must match exactly",
            )
        boolean_fields = tuple(
            field
            for field in expected
            if field
            not in {
                "schema_version",
                "design_admission",
                "covered_event_ids",
                "covered_parent_objectives",
                "semantic_evaluation_asset_version_id",
                "semantic_evaluation_hash",
            }
        )
        admission = value.get("design_admission", {})
        if work_requirements and (
            not isinstance(admission, Mapping)
            or admission.get("mode")
            not in {"STRICT_QUALIFIED", "AUTHOR_SUPERVISED_DESIGN", "CREATIVE_VALIDATION"}
            or admission.get("literary_qualification") not in {"NOT_PROVEN", "NOT_RUN"}
        ):
            raise KernelError(
                "REALIZATION_DESIGN_ADMISSION_REQUIRED",
                "Proof must preserve its actual strict or author-supervised basis",
            )
        if any(not isinstance(value.get(field), bool) for field in boolean_fields):
            raise KernelError(
                "NARRATIVE_REALIZATION_INVALID",
                "realization proof decisions must be boolean",
            )
        creative = value.get("schema_version") == "narrative-realization-proof.v3"
        if creative and (admission.get("mode") != "CREATIVE_VALIDATION" or admission.get("literary_qualification") != "NOT_RUN"
                or any(value.get(field) is not False for field in boolean_fields)):
            raise KernelError("REALIZATION_VALIDATION_PROOF_INVALID", "Unexecuted semantic criteria must remain false")
        if not creative and admission.get("mode") == "CREATIVE_VALIDATION":
            raise KernelError("REALIZATION_VALIDATION_PROOF_INVALID", "Validation requires its separate proof version")
        if not creative and any(value.get(field) is not True for field in boolean_fields):
            raise KernelError(
                "REALIZATION_PROOF_FAILED",
                "all deterministic and independent proof gates must pass",
            )
        return cls(
            covered_event_ids=_strings(
                value.get("covered_event_ids"), "covered_event_ids"
            ),
            covered_parent_objectives=_strings(
                value.get("covered_parent_objectives"), "covered_parent_objectives"
            ),
            **{
                (
                    "causal_escalation_proven"
                    if field == "causal_alignment_proven"
                    else field
                ): bool(value[field])
                for field in boolean_fields
            },
            schema_version=str(value["schema_version"]),
            design_admission=dict(admission),
            semantic_evaluation_asset_version_id=_required(
                value.get("semantic_evaluation_asset_version_id"),
                "semantic_evaluation_asset_version_id",
            ),
            semantic_evaluation_hash=_hash(
                value.get("semantic_evaluation_hash"), "semantic_evaluation_hash"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        value = _json_value(asdict(self))
        if self.schema_version in {"narrative-realization-proof.v2", "narrative-realization-proof.v3"}:
            value["causal_alignment_proven"] = value.pop("causal_escalation_proven")
        else:
            value.pop("design_admission")
        return value


@dataclass(frozen=True, slots=True)
class NarrativeRealizationContract:
    realization_id: str
    project_id: str
    book_id: str
    chapter_group_plan_version_id: str
    chapter_group_content_hash: str
    chapter_range: tuple[int, int]
    foundation_set_digest: str
    accepted_boundary: AcceptedBoundaryBinding
    arc_working_set_digest: str
    arc_plan_bindings: tuple[ArcPlanBinding, ...]
    events: tuple[NarrativeRealizationEvent, ...]
    proof: NarrativeRealizationProof
    content_asset_version_id: str
    content_hash: str
    proof_asset_version_id: str
    proof_hash: str
    lifecycle: NarrativeRealizationLifecycle
    contract_digest: str
    schema_version: str = NARRATIVE_REALIZATION_SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "NarrativeRealizationContract":
        allowed = {
            "schema_version",
            "realization_id",
            "project_id",
            "book_id",
            "chapter_group_plan_version_id",
            "chapter_group_content_hash",
            "chapter_range",
            "foundation_set_digest",
            "accepted_boundary",
            "arc_working_set_digest",
            "arc_plan_bindings",
            "events",
            "proof",
            "content_asset_version_id",
            "content_hash",
            "proof_asset_version_id",
            "proof_hash",
            "lifecycle",
        }
        if set(value) != allowed or value.get("schema_version") not in {
            NARRATIVE_REALIZATION_SCHEMA_VERSION,
            "narrative-realization-contract.v2",
        }:
            raise KernelError(
                "NARRATIVE_REALIZATION_INVALID",
                "Narrative Realization fields/schema must match exactly",
            )
        chapter_range = value.get("chapter_range")
        if not isinstance(chapter_range, list) or len(chapter_range) != 2:
            raise KernelError(
                "REALIZATION_SLICE_INVALID",
                "realization chapter_range requires start and end",
            )
        start, end = chapter_range
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start <= 0
            or end < start
        ):
            raise KernelError(
                "REALIZATION_SLICE_INVALID", "realization chapter range is invalid"
            )
        raw_arcs = value.get("arc_plan_bindings")
        raw_events = value.get("events")
        raw_boundary = value.get("accepted_boundary")
        raw_proof = value.get("proof")
        if (
            not isinstance(raw_arcs, list)
            or (not raw_arcs and value["schema_version"] != "narrative-realization-contract.v2")
            or not isinstance(raw_events, list)
            or not raw_events
            or not isinstance(raw_boundary, Mapping)
            or not isinstance(raw_proof, Mapping)
        ):
            raise KernelError(
                "NARRATIVE_REALIZATION_INVALID",
                "realization requires Arc, event, boundary and proof contracts",
            )
        arcs = tuple(ArcPlanBinding.from_mapping(item) for item in raw_arcs)
        if len({item.arc_id for item in arcs}) != len(arcs) or len(
            {item.asset_version_id for item in arcs}
        ) != len(arcs):
            raise KernelError(
                "NARRATIVE_REALIZATION_INVALID", "Arc bindings must be unique"
            )
        work_requirements = (
            value["schema_version"] == "narrative-realization-contract.v2"
        )
        events = tuple(
            NarrativeRealizationEvent.from_mapping(
                item, work_requirements=work_requirements
            )
            for item in raw_events
        )
        if (
            raw_proof.get("schema_version") in {"narrative-realization-proof.v2", "narrative-realization-proof.v3"}
        ) != work_requirements:
            raise KernelError(
                "REALIZATION_PROOF_VERSION_DRIFT",
                "Realization and proof semantics must match",
            )
        proof = NarrativeRealizationProof.from_mapping(raw_proof)
        _validate_event_chain(
            events, start=start, end=end, work_requirements=work_requirements
        )
        event_ids = tuple(item.event_id for item in events)
        if set(proof.covered_event_ids) != set(event_ids) or len(
            proof.covered_event_ids
        ) != len(event_ids):
            raise KernelError(
                "REALIZATION_PROOF_INCOMPLETE",
                "proof must cover every planned realization event exactly",
            )
        body = dict(value)
        contract_digest = realization_hash(body)
        accepted_boundary = AcceptedBoundaryBinding.from_mapping(raw_boundary)
        if accepted_boundary.accepted_through_chapter != start - 1:
            raise KernelError(
                "REALIZATION_SLICE_INVALID",
                "realization must begin immediately after its accepted boundary",
            )
        return cls(
            realization_id=_required(value.get("realization_id"), "realization_id"),
            project_id=_required(value.get("project_id"), "project_id"),
            book_id=_required(value.get("book_id"), "book_id"),
            chapter_group_plan_version_id=_required(
                value.get("chapter_group_plan_version_id"),
                "chapter_group_plan_version_id",
            ),
            chapter_group_content_hash=_hash(
                value.get("chapter_group_content_hash"),
                "chapter_group_content_hash",
            ),
            chapter_range=(start, end),
            foundation_set_digest=_hash(
                value.get("foundation_set_digest"), "foundation_set_digest"
            ),
            accepted_boundary=accepted_boundary,
            arc_working_set_digest=_hash(
                value.get("arc_working_set_digest"), "arc_working_set_digest"
            ),
            arc_plan_bindings=arcs,
            events=events,
            proof=proof,
            content_asset_version_id=_required(
                value.get("content_asset_version_id"), "content_asset_version_id"
            ),
            content_hash=_hash(value.get("content_hash"), "content_hash"),
            proof_asset_version_id=_required(
                value.get("proof_asset_version_id"), "proof_asset_version_id"
            ),
            proof_hash=_hash(value.get("proof_hash"), "proof_hash"),
            lifecycle=NarrativeRealizationLifecycle(str(value.get("lifecycle") or "")),
            contract_digest=contract_digest,
            schema_version=str(value["schema_version"]),
        )

    @property
    def event_ids(self) -> tuple[str, ...]:
        return tuple(item.event_id for item in self.events)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("contract_digest")
        value["events"] = [event.to_dict() for event in self.events]
        value["proof"] = self.proof.to_dict()
        return _json_value(value)


def _validate_event_chain(
    events: tuple[NarrativeRealizationEvent, ...],
    *,
    start: int,
    end: int,
    work_requirements: bool = False,
) -> None:
    ids = [item.event_id for item in events]
    if len(set(ids)) != len(ids):
        raise KernelError(
            "REALIZATION_EVENT_IDENTITY_INVALID", "event identities must be unique"
        )
    positions = {event_id: index for index, event_id in enumerate(ids)}
    chapters = {item.chapter_number for item in events}
    if any(item.chapter_number < start or item.chapter_number > end for item in events):
        raise KernelError(
            "REALIZATION_SLICE_INVALID",
            "every event must belong to the declared ChapterGroup range",
        )
    if chapters != set(range(start, end + 1)):
        raise KernelError(
            "REALIZATION_SLICE_INVALID",
            "realization events must cover every Chapter slice in the group",
        )
    for index, event in enumerate(events):
        if index and event.required and not event.causes and not work_requirements:
            raise KernelError(
                "REALIZATION_CAUSALITY_INVALID",
                f"every non-root required event needs an earlier cause; event={event.event_id}",
            )
        for cause in event.causes:
            if cause not in positions or positions[cause] >= index:
                raise KernelError(
                    "REALIZATION_CAUSALITY_INVALID",
                    "event causes must identify earlier planned events; "
                    f"event={event.event_id}, cause={cause}",
                )
            if event.event_id not in events[positions[cause]].next_event_ids:
                raise KernelError(
                    "REALIZATION_CAUSALITY_INVALID",
                    "cause/next-event references must agree in both directions; "
                    f"event={event.event_id} lists cause={cause}, "
                    f"but {cause}.next_event_ids omits {event.event_id}",
                )
        for following in event.next_event_ids:
            if following not in positions or positions[following] <= index:
                raise KernelError(
                    "REALIZATION_CAUSALITY_INVALID",
                    "next-event references must identify later planned events; "
                    f"event={event.event_id}, next_event_id={following}",
                )


def validate_narrative_realization_event_chain(
    events: list[Mapping[str, Any]],
    *,
    chapter_range: tuple[int, int],
    work_requirements: bool = False,
) -> tuple[NarrativeRealizationEvent, ...]:

    typed = tuple(
        NarrativeRealizationEvent.from_mapping(
            item, work_requirements=work_requirements
        )
        for item in events
    )
    if not typed:
        raise KernelError(
            "NARRATIVE_REALIZATION_INVALID",
            "ChapterGroup requires at least one causal realization event",
        )
    _validate_event_chain(
        typed,
        start=chapter_range[0],
        end=chapter_range[1],
        work_requirements=work_requirements,
    )
    return typed


__all__ = [
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
