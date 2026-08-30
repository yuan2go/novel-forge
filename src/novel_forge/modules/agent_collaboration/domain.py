from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping


class NarrativeScopeType(StrEnum):
    BOOK = "BOOK"
    VOLUME = "VOLUME"
    ARC = "ARC"
    CHAPTER_GROUP = "CHAPTER_GROUP"
    CHAPTER = "CHAPTER"
    SCENE = "SCENE"


class KnowledgeVisibility(StrEnum):
    AUTHOR_KNOWLEDGE = "AUTHOR_KNOWLEDGE"
    CHARACTER_KNOWLEDGE = "CHARACTER_KNOWLEDGE"
    READER_KNOWLEDGE = "READER_KNOWLEDGE"
    PUBLIC_CANON = "PUBLIC_CANON"
    HIDDEN_PLANNING = "HIDDEN_PLANNING"


class AgentMessageType(StrEnum):
    PROPOSAL = "PROPOSAL"
    CHALLENGE = "CHALLENGE"
    COUNTER_PROPOSAL = "COUNTER_PROPOSAL"
    REVISION = "REVISION"
    EVIDENCE = "EVIDENCE"
    IMPACT_ASSESSMENT = "IMPACT_ASSESSMENT"
    SUPPORT = "SUPPORT"
    OBJECTION = "OBJECTION"
    EVALUATION = "EVALUATION"
    SCOPE_EXPANSION_REQUEST = "SCOPE_EXPANSION_REQUEST"
    ESCALATION_REQUEST = "ESCALATION_REQUEST"
    DECISION_RECOMMENDATION = "DECISION_RECOMMENDATION"
    AUTHORITY_DECISION = "AUTHORITY_DECISION"


class SessionStatus(StrEnum):
    CREATED = "CREATED"
    SCOPE_FROZEN = "SCOPE_FROZEN"
    PARTICIPANTS_ASSIGNED = "PARTICIPANTS_ASSIGNED"
    INITIAL_PROPOSAL_PENDING = "INITIAL_PROPOSAL_PENDING"
    DELIBERATING = "DELIBERATING"
    REVISION_PENDING = "REVISION_PENDING"
    EVALUATING = "EVALUATING"
    CONSENSUS_REACHED = "CONSENSUS_REACHED"
    AUTHORITY_DECISION_PENDING = "AUTHORITY_DECISION_PENDING"
    ACCEPTED = "ACCEPTED"
    COMMITTED = "COMMITTED"
    SCOPE_VIOLATION = "SCOPE_VIOLATION"
    CONFLICT_UNRESOLVED = "CONFLICT_UNRESOLVED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    MAX_ROUNDS_REACHED = "MAX_ROUNDS_REACHED"
    HUMAN_DECISION_REQUIRED = "HUMAN_DECISION_REQUIRED"
    ESCALATED = "ESCALATED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class DomainAcceptance(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    DEFERRED = "DEFERRED"
    REPLAN_REQUIRED = "REPLAN_REQUIRED"
    HUMAN_DECISION_REQUIRED = "HUMAN_DECISION_REQUIRED"


class ConflictSeverity(StrEnum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    BLOCKING = "BLOCKING"


class ConflictStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    ACCEPTED_NON_BLOCKING = "ACCEPTED_NON_BLOCKING"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"


class CollaborationDecisionType(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    DEFERRED = "DEFERRED"
    REPLAN_REQUIRED = "REPLAN_REQUIRED"
    HUMAN_DECISION_REQUIRED = "HUMAN_DECISION_REQUIRED"
    SCOPE_EXPANSION_APPROVED = "SCOPE_EXPANSION_APPROVED"
    SCOPE_EXPANSION_REJECTED = "SCOPE_EXPANSION_REJECTED"


@dataclass(frozen=True, slots=True)
class NarrativeScope:
    kind: NarrativeScopeType
    book_id: str
    volume_id: str = ""
    arc_id: str = ""
    chapter_group_id: str = ""
    chapter_id: str = ""
    scene_id: str = ""

    def __post_init__(self) -> None:
        kind = _enum(NarrativeScopeType, self.kind)
        object.__setattr__(self, "kind", kind)
        required = {
            NarrativeScopeType.BOOK: {"book_id"},
            NarrativeScopeType.VOLUME: {"book_id", "volume_id"},
            # Arc is a semantic graph dimension and is not a Volume ancestor.
            NarrativeScopeType.ARC: {"book_id", "arc_id"},
            NarrativeScopeType.CHAPTER_GROUP: {
                "book_id",
                "volume_id",
                "chapter_group_id",
            },
            NarrativeScopeType.CHAPTER: {
                "book_id",
                "volume_id",
                "chapter_group_id",
                "chapter_id",
            },
            NarrativeScopeType.SCENE: {
                "book_id",
                "volume_id",
                "chapter_group_id",
                "chapter_id",
                "scene_id",
            },
        }[kind]
        allowed = (
            required
            | ({"volume_id"} if kind is NarrativeScopeType.ARC else set())
            | (
                {"arc_id"}
                if kind
                in {
                    NarrativeScopeType.CHAPTER_GROUP,
                    NarrativeScopeType.CHAPTER,
                    NarrativeScopeType.SCENE,
                }
                else set()
            )
        )
        for field_name in (
            "book_id",
            "volume_id",
            "arc_id",
            "chapter_group_id",
            "chapter_id",
            "scene_id",
        ):
            value = str(getattr(self, field_name) or "").strip()
            object.__setattr__(self, field_name, value)
            if field_name in required and not value:
                raise ValueError(f"{kind.value} narrative scope requires {field_name}")
            if field_name not in allowed and value:
                raise ValueError(
                    f"{kind.value} narrative scope cannot set {field_name}"
                )

    def contains(self, other: NarrativeScope) -> bool:
        if not isinstance(other, NarrativeScope):
            return False
        if self.book_id != other.book_id:
            return False
        if self.kind is NarrativeScopeType.BOOK:
            return True
        if self.kind is NarrativeScopeType.ARC:
            return self.arc_id == other.arc_id
        containment = {
            NarrativeScopeType.VOLUME: ("volume_id",),
            NarrativeScopeType.CHAPTER_GROUP: ("volume_id", "chapter_group_id"),
            NarrativeScopeType.CHAPTER: ("volume_id", "chapter_group_id", "chapter_id"),
            NarrativeScopeType.SCENE: (
                "volume_id",
                "chapter_group_id",
                "chapter_id",
                "scene_id",
            ),
        }
        fields = containment.get(self.kind, ())
        other_fields = containment.get(other.kind, ())
        return len(fields) <= len(other_fields) and all(
            getattr(self, field_name) == getattr(other, field_name)
            for field_name in fields
        )

    def to_dict(self) -> dict[str, Any]:
        return _to_plain(self)


@dataclass(frozen=True, slots=True)
class AssetReadScope:
    allowed_asset_types: tuple[str, ...]
    asset_version_ids: tuple[str, ...]
    forbidden_asset_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _freeze_strings(self, "allowed_asset_types")
        _freeze_strings(self, "asset_version_ids")
        _freeze_strings(self, "forbidden_asset_types")
        if set(self.allowed_asset_types) & set(self.forbidden_asset_types):
            raise ValueError("asset read scope cannot both allow and forbid a type")

    def allows_version(self, asset_version_id: str) -> bool:
        return not self.asset_version_ids or asset_version_id in self.asset_version_ids


@dataclass(frozen=True, slots=True)
class ProposalScope:
    allowed_asset_types: tuple[str, ...]
    allowed_change_types: tuple[str, ...]
    forbidden_asset_types: tuple[str, ...] = ()
    forbidden_change_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "allowed_asset_types",
            "allowed_change_types",
            "forbidden_asset_types",
            "forbidden_change_types",
        ):
            _freeze_strings(self, name)
        if set(self.allowed_asset_types) & set(self.forbidden_asset_types):
            raise ValueError("proposal asset type is both allowed and forbidden")
        if set(self.allowed_change_types) & set(self.forbidden_change_types):
            raise ValueError("proposal change type is both allowed and forbidden")

    def allows(self, *, asset_type: str, change_type: str) -> bool:
        return (
            asset_type in self.allowed_asset_types
            and asset_type not in self.forbidden_asset_types
            and change_type in self.allowed_change_types
            and change_type not in self.forbidden_change_types
        )


@dataclass(frozen=True, slots=True)
class AuthorityScope:
    authority_type: str
    allowed_narrative_scopes: tuple[NarrativeScopeType, ...]
    allowed_change_types: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.authority_type.strip():
            raise ValueError("authority scope requires authority_type")
        object.__setattr__(
            self,
            "allowed_narrative_scopes",
            tuple(
                _enum(NarrativeScopeType, item)
                for item in self.allowed_narrative_scopes
            ),
        )
        _freeze_strings(self, "allowed_change_types")
        if not self.allowed_narrative_scopes or not self.allowed_change_types:
            raise ValueError("authority scope is incomplete")

    def can_accept(self, authority_type: str, change: ProposedAssetChange) -> bool:
        return (
            authority_type == self.authority_type
            and change.narrative_scope.kind in self.allowed_narrative_scopes
            and change.change_type in self.allowed_change_types
        )


@dataclass(frozen=True, slots=True)
class TemporalScope:
    past_locked_through: int
    active_range: tuple[int, int]
    forecast_horizon: int
    published_boundary: int

    def __post_init__(self) -> None:
        if (
            self.past_locked_through < 0
            or self.forecast_horizon < 0
            or self.published_boundary < 0
            or len(self.active_range) != 2
        ):
            raise ValueError("temporal scope values must be non-negative")
        start, end = self.active_range
        if (
            start <= max(self.past_locked_through, self.published_boundary)
            or end < start
        ):
            raise ValueError(
                "temporal active range overlaps locked or published history"
            )
        if end > self.forecast_horizon:
            raise ValueError("temporal active range exceeds forecast horizon")


@dataclass(frozen=True, slots=True)
class KnowledgeVisibilityScope:
    allowed: tuple[KnowledgeVisibility, ...]

    def __post_init__(self) -> None:
        normalized = tuple(_enum(KnowledgeVisibility, item) for item in self.allowed)
        if not normalized:
            raise ValueError("knowledge visibility scope cannot be empty")
        object.__setattr__(self, "allowed", normalized)


@dataclass(frozen=True, slots=True)
class AgentScopeContract:
    scope_contract_id: str
    version: int
    narrative: NarrativeScope
    asset_read: AssetReadScope
    proposal: ProposalScope
    authority: AuthorityScope
    temporal: TemporalScope
    knowledge: KnowledgeVisibilityScope

    def __post_init__(self) -> None:
        if not self.scope_contract_id.strip() or self.version <= 0:
            raise ValueError("scope contract identity/version is invalid")

    @property
    def contract_hash(self) -> str:
        return _hash(self)

    def freeze(self, *, snapshot_id: str, authority_id: str) -> ScopeSnapshot:
        return ScopeSnapshot(
            snapshot_id=snapshot_id,
            scope_contract_id=self.scope_contract_id,
            scope_contract_version=self.version,
            authority_id=authority_id,
            contract=self,
            scope_hash=self.contract_hash,
        )


@dataclass(frozen=True, slots=True)
class ScopeSnapshot:
    snapshot_id: str
    scope_contract_id: str
    scope_contract_version: int
    authority_id: str
    contract: AgentScopeContract
    scope_hash: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.snapshot_id.strip(),
                self.scope_contract_id.strip(),
                self.authority_id.strip(),
                self.scope_hash.strip(),
            )
        ):
            raise ValueError("scope snapshot is incomplete")
        if (
            self.scope_contract_id != self.contract.scope_contract_id
            or self.scope_contract_version != self.contract.version
            or self.scope_hash != self.contract.contract_hash
        ):
            raise ValueError("scope snapshot differs from its immutable contract")

    def to_dict(self) -> dict[str, Any]:
        return _to_plain(self)


@dataclass(frozen=True, slots=True)
class ProposedAssetChange:
    asset_type: str
    asset_version_id: str
    narrative_scope: NarrativeScope
    change_type: str
    knowledge_visibility: KnowledgeVisibility
    chapter_number: int | None = None
    touches_published_content: bool = False

    def __post_init__(self) -> None:
        if not self.asset_type.strip() or not self.change_type.strip():
            raise ValueError("proposed change requires asset_type and change_type")
        object.__setattr__(
            self,
            "knowledge_visibility",
            _enum(KnowledgeVisibility, self.knowledge_visibility),
        )
        if self.chapter_number is not None and self.chapter_number <= 0:
            raise ValueError("proposed change chapter_number must be positive")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ProposedAssetChange:
        narrative = payload.get("narrative_scope")
        if not isinstance(narrative, Mapping):
            raise ValueError("proposed change requires narrative_scope")
        return cls(
            asset_type=str(payload.get("asset_type") or ""),
            asset_version_id=str(payload.get("asset_version_id") or ""),
            narrative_scope=NarrativeScope(**dict(narrative)),
            change_type=str(payload.get("change_type") or ""),
            knowledge_visibility=_enum(
                KnowledgeVisibility,
                payload.get("knowledge_visibility"),
            ),
            chapter_number=(
                None
                if payload.get("chapter_number") is None
                else int(payload["chapter_number"])
            ),
            touches_published_content=bool(
                payload.get("touches_published_content", False)
            ),
        )


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    agent_id: str
    version: int
    agent_type: str
    domain: str
    role: str
    capability_refs: tuple[str, ...]
    input_contract_ref: str
    output_contract_ref: str
    authority_scope_ref: str
    default_scope_policy_ref: str
    allowed_tools: tuple[str, ...]
    allowed_context_types: tuple[str, ...]
    execution_policy_ref: str
    approval_policy_ref: str
    quality_policy_ref: str
    status: str

    def __post_init__(self) -> None:
        required = tuple(
            str(getattr(self, name) or "").strip()
            for name in (
                "agent_id",
                "agent_type",
                "domain",
                "role",
                "input_contract_ref",
                "output_contract_ref",
                "authority_scope_ref",
                "default_scope_policy_ref",
                "execution_policy_ref",
                "approval_policy_ref",
                "quality_policy_ref",
                "status",
            )
        )
        if self.version <= 0 or not all(required):
            raise ValueError("AgentDefinition identity/contracts are incomplete")
        for name in (
            "capability_refs",
            "allowed_tools",
            "allowed_context_types",
        ):
            _freeze_strings(self, name)
            if not getattr(self, name):
                raise ValueError(f"AgentDefinition {name} cannot be empty")

    @property
    def definition_hash(self) -> str:
        return _hash(self)


@dataclass(frozen=True, slots=True)
class AgentCapability:
    capability_id: str
    version: int
    domain: str
    input_schema_ref: str
    output_schema_ref: str
    supported_message_types: tuple[AgentMessageType, ...]
    supported_scope_types: tuple[str, ...]
    risk_class: str
    execution_requirements: Mapping[str, Any]
    qualification_status: str

    def __post_init__(self) -> None:
        if self.version <= 0 or not all(
            str(getattr(self, name) or "").strip()
            for name in (
                "capability_id",
                "domain",
                "input_schema_ref",
                "output_schema_ref",
                "risk_class",
                "qualification_status",
            )
        ):
            raise ValueError("AgentCapability is incomplete")
        object.__setattr__(
            self,
            "supported_message_types",
            tuple(
                _enum(AgentMessageType, item) for item in self.supported_message_types
            ),
        )
        _freeze_strings(self, "supported_scope_types")
        object.__setattr__(
            self,
            "execution_requirements",
            _freeze_mapping(self.execution_requirements),
        )

    @property
    def capability_hash(self) -> str:
        return _hash(self)


@dataclass(frozen=True, slots=True)
class Participant:
    agent_id: str
    agent_definition_version: int
    role: str

    def __post_init__(self) -> None:
        if (
            not self.agent_id.strip()
            or not self.role.strip()
            or self.agent_definition_version <= 0
        ):
            raise ValueError("participant is incomplete")


@dataclass(frozen=True, slots=True)
class ParticipantSnapshot:
    snapshot_id: str
    participants: tuple[Participant, ...]
    participant_hash: str

    @classmethod
    def freeze(
        cls, *, snapshot_id: str, participants: tuple[Participant, ...]
    ) -> ParticipantSnapshot:
        if len({item.agent_id for item in participants}) != len(participants):
            raise ValueError("participant snapshot contains duplicate agent")
        if not participants:
            raise ValueError("participant snapshot cannot be empty")
        return cls(
            snapshot_id=snapshot_id,
            participants=tuple(participants),
            participant_hash=_hash(participants),
        )

    def __post_init__(self) -> None:
        if (
            not self.snapshot_id.strip()
            or not self.participants
            or self.participant_hash != _hash(self.participants)
        ):
            raise ValueError("participant snapshot is invalid")

    def has_role(self, role: str) -> bool:
        return any(item.role == role for item in self.participants)


@dataclass(frozen=True, slots=True)
class AgentWorkOrder:
    work_order_id: str
    collaboration_session_id: str
    turn_id: str
    operation_id: str
    attempt_id: str
    fencing_token: int
    agent_id: str
    agent_definition_version: int
    capability: str
    message_type: AgentMessageType
    business_goal: str
    current_issue: str
    scope_snapshot_ref: str
    participant_snapshot_ref: str
    input_asset_versions: tuple[str, ...]
    candidate_version_ref: str
    context_bundle_ref: str
    evidence_refs: tuple[str, ...]
    must_preserve: tuple[str, ...]
    must_change: tuple[str, ...]
    forbidden_changes: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    risk_level: str
    budget_policy_ref: str
    timeout_policy_ref: str
    approval_policy_ref: str
    failure_policy: str
    continuation_policy: str
    project_id: str
    workspace_id: str
    book_id: str
    route_snapshot_ref: str
    input_manifest_ref: str
    capability_version: int
    execution_capability: str

    def __post_init__(self) -> None:
        required = (
            self.work_order_id,
            self.collaboration_session_id,
            self.turn_id,
            self.operation_id,
            self.attempt_id,
            self.agent_id,
            self.capability,
            self.business_goal,
            self.current_issue,
            self.scope_snapshot_ref,
            self.participant_snapshot_ref,
            self.context_bundle_ref,
            self.risk_level,
            self.budget_policy_ref,
            self.timeout_policy_ref,
            self.approval_policy_ref,
            self.failure_policy,
            self.continuation_policy,
            self.project_id,
            self.workspace_id,
            self.book_id,
            self.route_snapshot_ref,
            self.input_manifest_ref,
            self.execution_capability,
        )
        if (
            any(not str(item).strip() for item in required)
            or self.fencing_token <= 0
            or self.agent_definition_version <= 0
            or self.capability_version <= 0
        ):
            raise ValueError("AgentWorkOrder is incomplete")
        object.__setattr__(
            self, "message_type", _enum(AgentMessageType, self.message_type)
        )
        for name in (
            "input_asset_versions",
            "evidence_refs",
            "must_preserve",
            "must_change",
            "forbidden_changes",
            "acceptance_criteria",
        ):
            _freeze_strings(self, name)

    def to_context(self) -> dict[str, Any]:
        return _to_plain(self)


@dataclass(frozen=True, slots=True)
class AgentOutputEnvelope:
    output_id: str
    session_id: str
    turn_id: str
    agent_id: str
    message_type: AgentMessageType
    structured_payload: Mapping[str, Any]
    natural_language_explanation: str
    source_asset_versions: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    assumptions: tuple[str, ...]
    confidence: float
    affected_assets: tuple[str, ...]
    proposed_changes: tuple[ProposedAssetChange, ...]
    preserved_constraints: tuple[str, ...]
    accessed_knowledge: tuple[KnowledgeVisibility, ...]
    unresolved_questions: tuple[str, ...]
    risk_level: str
    requested_next_action: str
    execution_evidence_ref: str

    def __post_init__(self) -> None:
        required = (
            self.output_id,
            self.session_id,
            self.turn_id,
            self.agent_id,
            self.natural_language_explanation,
            self.risk_level,
            self.requested_next_action,
            self.execution_evidence_ref,
        )
        if any(not str(item).strip() for item in required):
            raise ValueError("AgentOutputEnvelope is incomplete")
        object.__setattr__(
            self, "message_type", _enum(AgentMessageType, self.message_type)
        )
        if (
            not isinstance(self.structured_payload, Mapping)
            or not self.structured_payload
        ):
            raise ValueError("AgentOutputEnvelope structured_payload is required")
        object.__setattr__(
            self, "structured_payload", _freeze_mapping(self.structured_payload)
        )
        confidence = float(self.confidence)
        if not 0 <= confidence <= 1:
            raise ValueError("AgentOutputEnvelope confidence must be between 0 and 1")
        object.__setattr__(self, "confidence", confidence)
        for name in (
            "source_asset_versions",
            "evidence_refs",
            "assumptions",
            "affected_assets",
            "preserved_constraints",
            "unresolved_questions",
        ):
            _freeze_strings(self, name)
        object.__setattr__(self, "proposed_changes", tuple(self.proposed_changes))
        object.__setattr__(
            self,
            "accessed_knowledge",
            tuple(_enum(KnowledgeVisibility, item) for item in self.accessed_knowledge),
        )

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        execution_evidence_ref: str,
    ) -> AgentOutputEnvelope:
        changes = payload.get("proposed_changes") or ()
        if not isinstance(changes, (list, tuple)):
            raise ValueError("AgentOutputEnvelope proposed_changes must be an array")
        return cls(
            output_id=str(payload.get("output_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            turn_id=str(payload.get("turn_id") or ""),
            agent_id=str(payload.get("agent_id") or ""),
            message_type=_enum(
                AgentMessageType,
                payload.get("message_type"),
            ),
            structured_payload=_required_mapping(payload, "structured_payload"),
            natural_language_explanation=str(
                payload.get("natural_language_explanation") or ""
            ),
            source_asset_versions=_strings(payload.get("source_asset_versions")),
            evidence_refs=_strings(payload.get("evidence_refs")),
            assumptions=_strings(payload.get("assumptions")),
            confidence=float(payload.get("confidence", -1)),
            affected_assets=_strings(payload.get("affected_assets")),
            proposed_changes=tuple(
                item
                if isinstance(item, ProposedAssetChange)
                else ProposedAssetChange.from_mapping(_mapping(item, "proposed change"))
                for item in changes
            ),
            preserved_constraints=_strings(payload.get("preserved_constraints")),
            accessed_knowledge=tuple(
                _enum(KnowledgeVisibility, item)
                for item in (payload.get("accessed_knowledge") or ())
            ),
            unresolved_questions=_strings(payload.get("unresolved_questions")),
            risk_level=str(payload.get("risk_level") or ""),
            requested_next_action=str(payload.get("requested_next_action") or ""),
            execution_evidence_ref=execution_evidence_ref,
        )

    def to_dict(self) -> dict[str, Any]:
        return _to_plain(self)


@dataclass(frozen=True, slots=True)
class ScopeValidationResult:
    compliant: bool
    violations: tuple[str, ...]
    requires_scope_expansion: bool


class ScopePolicy:
    @staticmethod
    def validate_output(
        snapshot: ScopeSnapshot, envelope: AgentOutputEnvelope
    ) -> ScopeValidationResult:
        contract = snapshot.contract
        violations: list[str] = []
        requires_expansion = False
        for version_id in envelope.source_asset_versions:
            if not contract.asset_read.allows_version(version_id):
                violations.append("ASSET_READ_SCOPE_VIOLATION")
        if any(
            visibility not in contract.knowledge.allowed
            for visibility in envelope.accessed_knowledge
        ):
            violations.append("KNOWLEDGE_VISIBILITY_VIOLATION")
        for change in envelope.proposed_changes:
            if not contract.narrative.contains(change.narrative_scope):
                violations.append("NARRATIVE_SCOPE_VIOLATION")
                requires_expansion = True
            if not contract.proposal.allows(
                asset_type=change.asset_type,
                change_type=change.change_type,
            ):
                violations.append("PROPOSAL_SCOPE_VIOLATION")
            if not contract.authority.can_accept(
                contract.authority.authority_type,
                change,
            ):
                violations.append("AUTHORITY_SCOPE_VIOLATION")
            if (
                change.touches_published_content
                or (
                    change.chapter_number is not None
                    and change.chapter_number <= contract.temporal.published_boundary
                )
                or (
                    change.chapter_number is not None
                    and change.chapter_number <= contract.temporal.past_locked_through
                )
            ):
                violations.append("PUBLISHED_BOUNDARY_VIOLATION")
            if change.knowledge_visibility not in contract.knowledge.allowed:
                violations.append("KNOWLEDGE_VISIBILITY_VIOLATION")
        ordered = tuple(dict.fromkeys(violations))
        return ScopeValidationResult(
            compliant=not ordered,
            violations=ordered,
            requires_scope_expansion=requires_expansion,
        )


@dataclass(frozen=True, slots=True)
class AgentConversationMessage:
    message_id: str
    session_id: str
    turn_id: str
    message_type: AgentMessageType
    sender_id: str
    recipient_ids: tuple[str, ...]
    target_proposal_id: str
    target_candidate_version_id: str
    scope_snapshot_ref: str
    evidence_refs: tuple[str, ...]
    parent_message_id: str
    structured_payload: Mapping[str, Any]
    natural_language: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "message_type", _enum(AgentMessageType, self.message_type)
        )
        if any(
            not str(item).strip()
            for item in (
                self.message_id,
                self.session_id,
                self.turn_id,
                self.sender_id,
                self.scope_snapshot_ref,
                self.natural_language,
            )
        ):
            raise ValueError("conversation message is incomplete")
        _freeze_strings(self, "recipient_ids")
        _freeze_strings(self, "evidence_refs")
        object.__setattr__(
            self, "structured_payload", _freeze_mapping(self.structured_payload)
        )
        targeted = {
            AgentMessageType.CHALLENGE,
            AgentMessageType.COUNTER_PROPOSAL,
            AgentMessageType.REVISION,
            AgentMessageType.OBJECTION,
            AgentMessageType.EVALUATION,
            AgentMessageType.SUPPORT,
            AgentMessageType.IMPACT_ASSESSMENT,
        }
        if self.message_type in targeted and not self.target_candidate_version_id:
            raise ValueError(
                f"{self.message_type.value} requires target candidate version"
            )


@dataclass(frozen=True, slots=True)
class AgentCollaborationSession:
    session_id: str
    project_id: str
    owner_authority: str
    business_goal: str
    issue_type: str
    scope_snapshot_ref: str
    participant_snapshot_ref: str
    current_candidate_version_ref: str
    status: SessionStatus
    round_number: int
    turn_number: int
    execution_count: int
    spent_budget: Decimal
    budget_ref: str
    termination_policy_ref: str
    created_operation_id: str
    saga_id: str
    authority_decision_ref: str
    last_turn_id: str
    persistence_version: int = 0
    attempt_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _enum(SessionStatus, self.status))
        object.__setattr__(self, "spent_budget", Decimal(self.spent_budget))
        if any(
            not str(item).strip()
            for item in (
                self.session_id,
                self.project_id,
                self.owner_authority,
                self.business_goal,
                self.issue_type,
                self.budget_ref,
                self.termination_policy_ref,
                self.created_operation_id,
                self.saga_id,
            )
        ):
            raise ValueError("collaboration session is incomplete")
        if (
            min(
                self.round_number,
                self.turn_number,
                self.execution_count,
                self.persistence_version,
            )
            < 0
        ):
            raise ValueError("collaboration counters cannot be negative")
        if self.spent_budget < 0:
            raise ValueError("collaboration spent budget cannot be negative")
        if self.attempt_id and not self.attempt_id.strip():
            raise ValueError("collaboration Attempt identity is invalid")

    def advance_turn(
        self, turn_id: str, *, cost: Decimal = Decimal("0")
    ) -> AgentCollaborationSession:
        if not turn_id.strip():
            raise ValueError("turn identity is required")
        if turn_id == self.last_turn_id:
            raise ValueError("duplicate turn cannot advance collaboration")
        return replace(
            self,
            turn_number=self.turn_number + 1,
            execution_count=self.execution_count + 1,
            spent_budget=self.spent_budget + Decimal(cost),
            last_turn_id=turn_id,
        )


class CollaborationStateMachine:
    _TRANSITIONS: Mapping[SessionStatus, frozenset[SessionStatus]] = {
        SessionStatus.CREATED: frozenset({SessionStatus.SCOPE_FROZEN}),
        SessionStatus.SCOPE_FROZEN: frozenset({SessionStatus.PARTICIPANTS_ASSIGNED}),
        SessionStatus.PARTICIPANTS_ASSIGNED: frozenset(
            {SessionStatus.INITIAL_PROPOSAL_PENDING}
        ),
        SessionStatus.INITIAL_PROPOSAL_PENDING: frozenset({SessionStatus.DELIBERATING}),
        SessionStatus.DELIBERATING: frozenset(
            {
                SessionStatus.REVISION_PENDING,
                SessionStatus.EVALUATING,
                SessionStatus.CONSENSUS_REACHED,
            }
        ),
        SessionStatus.REVISION_PENDING: frozenset(
            {SessionStatus.EVALUATING, SessionStatus.DELIBERATING}
        ),
        SessionStatus.EVALUATING: frozenset(
            {
                SessionStatus.CONSENSUS_REACHED,
                SessionStatus.REVISION_PENDING,
                SessionStatus.CONFLICT_UNRESOLVED,
            }
        ),
        SessionStatus.CONSENSUS_REACHED: frozenset(
            {SessionStatus.AUTHORITY_DECISION_PENDING}
        ),
        SessionStatus.AUTHORITY_DECISION_PENDING: frozenset(
            {
                SessionStatus.ACCEPTED,
                SessionStatus.REJECTED,
                SessionStatus.REVISION_PENDING,
                SessionStatus.HUMAN_DECISION_REQUIRED,
                SessionStatus.ESCALATED,
            }
        ),
        SessionStatus.ACCEPTED: frozenset({SessionStatus.COMMITTED}),
        SessionStatus.ESCALATED: frozenset({SessionStatus.REJECTED}),
    }
    _EXCEPTIONS = frozenset(
        {
            SessionStatus.SCOPE_VIOLATION,
            SessionStatus.CONFLICT_UNRESOLVED,
            SessionStatus.BUDGET_EXHAUSTED,
            SessionStatus.MAX_ROUNDS_REACHED,
            SessionStatus.HUMAN_DECISION_REQUIRED,
            SessionStatus.ESCALATED,
            SessionStatus.CANCELLED,
            SessionStatus.FAILED,
        }
    )
    _TERMINAL = frozenset(
        {
            SessionStatus.COMMITTED,
            SessionStatus.REJECTED,
            SessionStatus.CANCELLED,
            SessionStatus.FAILED,
        }
    )

    @classmethod
    def transition(
        cls,
        session: AgentCollaborationSession,
        target: SessionStatus,
    ) -> AgentCollaborationSession:
        target = _enum(SessionStatus, target)
        if target == session.status:
            return session
        if session.status in cls._TERMINAL:
            raise ValueError(
                f"illegal collaboration transition from terminal {session.status.value}"
            )
        allowed = cls._TRANSITIONS.get(session.status, frozenset())
        if target not in allowed and target not in cls._EXCEPTIONS:
            raise ValueError(
                f"illegal collaboration transition "
                f"{session.status.value} -> {target.value}"
            )
        return replace(session, status=target)


@dataclass(frozen=True, slots=True)
class CandidateVersion:
    candidate_version_id: str
    session_id: str
    candidate_type: str
    parent_version_ids: tuple[str, ...]
    originating_message_id: str
    originating_turn_id: str
    created_by_agent: str
    scope_snapshot_ref: str
    content_ref: str
    structured_diff: Mapping[str, Any]
    change_reason_refs: tuple[str, ...]
    preserved_constraints: tuple[str, ...]
    resolved_conflicts: tuple[str, ...]
    unresolved_conflicts: tuple[str, ...]
    validation_status: str

    def __post_init__(self) -> None:
        if any(
            not str(item).strip()
            for item in (
                self.candidate_version_id,
                self.session_id,
                self.candidate_type,
                self.originating_message_id,
                self.originating_turn_id,
                self.created_by_agent,
                self.scope_snapshot_ref,
                self.content_ref,
                self.validation_status,
            )
        ):
            raise ValueError("candidate version is incomplete")
        for name in (
            "parent_version_ids",
            "change_reason_refs",
            "preserved_constraints",
            "resolved_conflicts",
            "unresolved_conflicts",
        ):
            _freeze_strings(self, name)
        if self.candidate_version_id in self.parent_version_ids:
            raise ValueError("candidate version cannot be its own parent")
        object.__setattr__(
            self, "structured_diff", _freeze_mapping(self.structured_diff)
        )


@dataclass(frozen=True, slots=True)
class ConflictRecord:
    conflict_id: str
    session_id: str
    conflict_type: str
    severity: ConflictSeverity
    raised_by: str
    target_candidate_version: str
    conflicting_asset_versions: tuple[str, ...]
    claim: str
    evidence_refs: tuple[str, ...]
    affected_scopes: tuple[str, ...]
    affected_assets: tuple[str, ...]
    reader_outcome_impact: str
    continuity_impact: str
    ending_reachability_impact: str
    requested_resolution: str
    status: ConflictStatus
    resolution_ref: str
    authority_decision_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "severity", _enum(ConflictSeverity, self.severity))
        object.__setattr__(self, "status", _enum(ConflictStatus, self.status))
        if any(
            not str(item).strip()
            for item in (
                self.conflict_id,
                self.session_id,
                self.conflict_type,
                self.raised_by,
                self.target_candidate_version,
                self.claim,
                self.reader_outcome_impact,
                self.continuity_impact,
                self.ending_reachability_impact,
                self.requested_resolution,
            )
        ):
            raise ValueError("ConflictRecord is incomplete")
        for name in (
            "conflicting_asset_versions",
            "evidence_refs",
            "affected_scopes",
            "affected_assets",
        ):
            _freeze_strings(self, name)

    @property
    def is_blocking(self) -> bool:
        return (
            self.severity is ConflictSeverity.BLOCKING
            and self.status is ConflictStatus.OPEN
        )


@dataclass(frozen=True, slots=True)
class ScopeExpansionRequest:
    request_id: str
    session_id: str
    current_scope_snapshot_ref: str
    requested_scope: NarrativeScope
    reason: str
    affected_assets: tuple[str, ...]
    risk_level: str
    requesting_agent: str
    required_authority: str
    decision: str = "PENDING"
    decision_ref: str = ""

    def __post_init__(self) -> None:
        if any(
            not str(item).strip()
            for item in (
                self.request_id,
                self.session_id,
                self.current_scope_snapshot_ref,
                self.reason,
                self.risk_level,
                self.requesting_agent,
                self.required_authority,
                self.decision,
            )
        ):
            raise ValueError("ScopeExpansionRequest is incomplete")
        _freeze_strings(self, "affected_assets")


@dataclass(frozen=True, slots=True)
class CollaborationDecision:
    decision_id: str
    decision: CollaborationDecisionType
    authority_type: str
    authority_version: int
    session_id: str
    candidate_version_id: str
    accepted_changes: tuple[str, ...]
    rejected_changes: tuple[str, ...]
    deferred_changes: tuple[str, ...]
    accepted_with_objections: tuple[str, ...]
    unresolved_objections: tuple[str, ...]
    required_followup: tuple[str, ...]
    affected_asset_versions: tuple[str, ...]
    commit_policy_ref: str
    decision_evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "decision", _enum(CollaborationDecisionType, self.decision)
        )
        scope_expansion_decision = self.decision in {
            CollaborationDecisionType.SCOPE_EXPANSION_APPROVED,
            CollaborationDecisionType.SCOPE_EXPANSION_REJECTED,
        }
        if self.authority_version <= 0 or any(
            not str(item).strip()
            for item in (
                self.decision_id,
                self.authority_type,
                self.session_id,
                self.commit_policy_ref,
            )
        ):
            raise ValueError("CollaborationDecision is incomplete")
        if not scope_expansion_decision and not self.candidate_version_id.strip():
            raise ValueError(
                "non-scope CollaborationDecision requires candidate version"
            )
        if scope_expansion_decision and self.candidate_version_id:
            raise ValueError(
                "scope expansion decision cannot bind an unaccepted candidate"
            )
        for item in fields(self):
            if item.name in {
                "accepted_changes",
                "rejected_changes",
                "deferred_changes",
                "accepted_with_objections",
                "unresolved_objections",
                "required_followup",
                "affected_asset_versions",
                "decision_evidence",
            }:
                _freeze_strings(self, item.name)

    def validate_against(self, conflicts: tuple[ConflictRecord, ...]) -> None:
        if self.decision is CollaborationDecisionType.ACCEPTED and any(
            item.is_blocking for item in conflicts
        ):
            raise ValueError("Authority cannot accept an unresolved blocking conflict")


@dataclass(frozen=True, slots=True)
class TerminationContext:
    round_number: int
    turn_number: int
    execution_count: int
    spent_budget: Decimal
    participant_roles: frozenset[str]
    evaluation_roles: frozenset[str]
    blocking_conflicts: int
    major_issues: int
    scope_violations: int
    human_decision_required: bool


@dataclass(frozen=True, slots=True)
class TerminationEvaluation:
    must_stop: bool
    reasons: tuple[str, ...]
    recommended_status: SessionStatus | None


@dataclass(frozen=True, slots=True)
class TerminationPolicy:
    policy_id: str
    max_rounds: int
    max_turns: int
    max_executions: int
    max_budget: Decimal
    required_participant_roles: tuple[str, ...]
    required_evaluation_roles: tuple[str, ...]
    blocking_issue_threshold: int
    major_issue_threshold: int
    unresolved_conflict_policy: str
    scope_violation_policy: str
    consensus_policy: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_budget", Decimal(self.max_budget))
        if (
            not self.policy_id.strip()
            or min(self.max_rounds, self.max_turns, self.max_executions) <= 0
            or self.max_budget < 0
            or self.blocking_issue_threshold < 0
            or self.major_issue_threshold < 0
        ):
            raise ValueError("TerminationPolicy limits are invalid")
        if self.consensus_policy != "AUTHORITY_LED":
            raise ValueError("collaboration V1 only supports AUTHORITY_LED consensus")
        _freeze_strings(self, "required_participant_roles")
        _freeze_strings(self, "required_evaluation_roles")

    def evaluate(self, context: TerminationContext) -> TerminationEvaluation:
        reasons: list[str] = []
        status: SessionStatus | None = None
        missing_participants = set(self.required_participant_roles) - set(
            context.participant_roles
        )
        missing_evaluators = set(self.required_evaluation_roles) - set(
            context.evaluation_roles
        )
        if missing_participants:
            reasons.append("REQUIRED_PARTICIPANT_MISSING")
        if missing_evaluators:
            reasons.append("REQUIRED_EVALUATION_MISSING")
        if context.round_number >= self.max_rounds:
            reasons.append("MAX_ROUNDS_REACHED")
            status = SessionStatus.MAX_ROUNDS_REACHED
        if context.turn_number >= self.max_turns:
            reasons.append("MAX_TURNS_REACHED")
            status = status or SessionStatus.MAX_ROUNDS_REACHED
        if context.execution_count >= self.max_executions:
            reasons.append("MAX_EXECUTIONS_REACHED")
            status = status or SessionStatus.MAX_ROUNDS_REACHED
        if context.spent_budget >= self.max_budget:
            reasons.append("BUDGET_EXHAUSTED")
            status = SessionStatus.BUDGET_EXHAUSTED
        if (
            context.blocking_conflicts >= self.blocking_issue_threshold
            and self.blocking_issue_threshold > 0
        ):
            reasons.append("BLOCKING_CONFLICT")
            status = SessionStatus.CONFLICT_UNRESOLVED
        if context.major_issues > self.major_issue_threshold:
            reasons.append("MAJOR_ISSUE_THRESHOLD")
        if context.scope_violations:
            reasons.append("SCOPE_VIOLATION")
            status = SessionStatus.SCOPE_VIOLATION
        if context.human_decision_required:
            reasons.append("HUMAN_DECISION_REQUIRED")
            status = SessionStatus.HUMAN_DECISION_REQUIRED
        return TerminationEvaluation(bool(reasons), tuple(reasons), status)


def _scope_index(kind: NarrativeScopeType) -> int:
    return tuple(NarrativeScopeType).index(kind)


def _enum(enum_type: type[StrEnum], value: Any):
    return value if isinstance(value, enum_type) else enum_type(str(value))


def _freeze_strings(instance: object, name: str) -> None:
    object.__setattr__(instance, name, _strings(getattr(instance, name)))


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise ValueError("expected an array of strings")
    return tuple(str(item) for item in value)


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    def freeze(item: Any) -> Any:
        if isinstance(item, Mapping):
            return MappingProxyType(
                {str(key): freeze(child) for key, child in item.items()}
            )
        if isinstance(item, (list, tuple)):
            return tuple(freeze(child) for child in item)
        return item

    return freeze(dict(value))


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _required_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = _mapping(payload.get(key), key)
    if not value:
        raise ValueError(f"{key} cannot be empty")
    return value


def _to_plain(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _to_plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, frozenset, set)):
        return [_to_plain(item) for item in value]
    if is_dataclass(value):
        return {
            item.name: _to_plain(getattr(value, item.name))
            for item in fields(value)
            if not item.name.startswith("_")
        }
    return value


def _hash(value: Any) -> str:
    encoded = json.dumps(
        _to_plain(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "AgentCapability",
    "AgentCollaborationSession",
    "AgentConversationMessage",
    "AgentDefinition",
    "AgentMessageType",
    "AgentOutputEnvelope",
    "AgentScopeContract",
    "AgentWorkOrder",
    "AssetReadScope",
    "AuthorityScope",
    "CandidateVersion",
    "CollaborationDecision",
    "CollaborationDecisionType",
    "CollaborationStateMachine",
    "ConflictRecord",
    "ConflictSeverity",
    "ConflictStatus",
    "DomainAcceptance",
    "KnowledgeVisibility",
    "KnowledgeVisibilityScope",
    "NarrativeScope",
    "NarrativeScopeType",
    "Participant",
    "ParticipantSnapshot",
    "ProposalScope",
    "ProposedAssetChange",
    "ScopeExpansionRequest",
    "ScopePolicy",
    "ScopeSnapshot",
    "ScopeValidationResult",
    "SessionStatus",
    "TemporalScope",
    "TerminationContext",
    "TerminationEvaluation",
    "TerminationPolicy",
]
