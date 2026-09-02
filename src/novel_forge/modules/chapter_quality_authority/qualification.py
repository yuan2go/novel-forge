"""INVARIANT: engineering, narrative, editorial, Reader, and longitudinal evidence remain separate; a missing layer never becomes zero or a pass."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping


QUALITY_QUALIFICATION_SCHEMA = "novel-forge.quality-qualification.v1"
_MIGRATION_ID = re.compile(r"^[0-9]{8}_[0-9]{4}_[a-z0-9_]+$")


class CampaignLifecycle(StrEnum):
    DRAFT = "DRAFT"
    FROZEN = "FROZEN"
    RUNNING = "RUNNING"
    WAITING_HUMAN_EVIDENCE = "WAITING_HUMAN_EVIDENCE"
    EVALUATING = "EVALUATING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class EvidenceLayer(StrEnum):
    L1_HARD_CORRECTNESS = "L1_HARD_CORRECTNESS"
    L2_EDITORIAL_QUALITY = "L2_EDITORIAL_QUALITY"
    L3_READER_LONGITUDINAL = "L3_READER_LONGITUDINAL"


class EvidenceStatus(StrEnum):
    PASS = "PASS"
    PASS_WITH_LIMITATIONS = "PASS_WITH_LIMITATIONS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    NOT_PROVEN = "NOT_PROVEN"
    NOT_OBSERVED = "NOT_OBSERVED"
    WAITING_HUMAN_EVIDENCE = "WAITING_HUMAN_EVIDENCE"


class EvidenceSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    MAJOR = "MAJOR"
    SEVERE = "SEVERE"
    BLOCKING = "BLOCKING"


class QualificationStatus(StrEnum):
    PASS = "PASS"
    PASS_WITH_LIMITATIONS = "PASS_WITH_LIMITATIONS"
    FAIL = "FAIL"
    NOT_PROVEN = "NOT_PROVEN"


class HumanEvidenceStatus(StrEnum):
    WAITING_HUMAN_EVIDENCE = "WAITING_HUMAN_EVIDENCE"
    HUMAN_EVIDENCE_LIMITED = "HUMAN_EVIDENCE_LIMITED"
    BOUNDED_HUMAN_EVIDENCE = "BOUNDED_HUMAN_EVIDENCE"


_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "campaign_id",
        "campaign_version",
        "exact_release_sha",
        "migration_head",
        "protocol_version",
        "evaluation_profile_version",
        "quality_profile_version",
        "reader_outcome_profile_version",
        "project_id",
        "workspace_id",
        "book_id",
        "chapter_group_ranges",
        "provider_route_manifest",
        "capability_pack_manifest",
        "prompt_skill_lineage",
        "foundation_lineage",
        "planning_lineage",
        "realization_lineage",
        "context_policy",
        "baseline_protocol",
        "budget_policy",
        "required_evaluator_count",
    }
)
_MAPPING_FIELDS = (
    "provider_route_manifest",
    "capability_pack_manifest",
    "prompt_skill_lineage",
    "foundation_lineage",
    "planning_lineage",
    "realization_lineage",
    "context_policy",
    "baseline_protocol",
    "budget_policy",
)
_FULL_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("campaign manifest must be canonical JSON") from exc


def _required_text(payload: Mapping[str, Any], field_name: str) -> str:
    value = str(payload.get(field_name) or "").strip()
    if not value:
        raise ValueError(f"{field_name} is required")
    return value


@dataclass(frozen=True, slots=True)
class QualityCampaignManifest:
    schema_version: str
    campaign_id: str
    campaign_version: int
    exact_release_sha: str
    migration_head: str
    protocol_version: str
    evaluation_profile_version: str
    quality_profile_version: str
    reader_outcome_profile_version: str
    project_id: str
    workspace_id: str
    book_id: str
    chapter_group_ranges: tuple[tuple[int, int], ...]
    required_evaluator_count: int
    _canonical_payload: str = field(repr=False)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "QualityCampaignManifest":
        if not isinstance(raw, Mapping):
            raise ValueError("campaign manifest must be an object")
        supplied = frozenset(str(key) for key in raw)
        missing = sorted(_MANIFEST_FIELDS - supplied)
        unknown = sorted(supplied - _MANIFEST_FIELDS)
        if missing:
            raise ValueError("campaign manifest lacks fields: " + ", ".join(missing))
        if unknown:
            raise ValueError(
                "campaign manifest has unknown fields: " + ", ".join(unknown)
            )

        canonical = _canonical_json(dict(raw))
        payload = json.loads(canonical)
        if payload["schema_version"] != QUALITY_QUALIFICATION_SCHEMA:
            raise ValueError("unsupported quality qualification schema_version")

        release_sha = _required_text(payload, "exact_release_sha").lower()
        if not _FULL_GIT_SHA.fullmatch(release_sha):
            raise ValueError("exact_release_sha must be a full Git SHA")
        migration_head = _required_text(payload, "migration_head")
        if not _MIGRATION_ID.fullmatch(migration_head):
            raise ValueError("migration_head must identify an applied migration")

        campaign_version = int(payload.get("campaign_version") or 0)
        if campaign_version <= 0:
            raise ValueError("campaign_version must be positive")
        required_evaluators = int(payload.get("required_evaluator_count") or 0)
        if required_evaluators < 2:
            raise ValueError("required_evaluator_count must be at least two")

        raw_ranges = payload.get("chapter_group_ranges")
        if not isinstance(raw_ranges, list) or not all(
            isinstance(item, list) and len(item) == 2 for item in raw_ranges
        ):
            raise ValueError("chapter_group_ranges must be a list of pairs")
        ranges = tuple((int(item[0]), int(item[1])) for item in raw_ranges)
        if not ranges:
            raise ValueError("chapter_group_ranges must not be empty")
        expected_start = ranges[0][0]
        for start, end in ranges:
            if start <= 0 or end < start:
                raise ValueError("chapter_group_ranges must contain positive ranges")
            if start != expected_start:
                raise ValueError("chapter_group_ranges must be ordered and contiguous")
            expected_start = end + 1

        for name in _MAPPING_FIELDS:
            value = payload.get(name)
            if not isinstance(value, dict) or not value:
                raise ValueError(f"{name} must be a non-empty object")
        budget = payload["budget_policy"]
        chapter_count = sum(end - start + 1 for start, end in ranges)
        if int(budget.get("chapter_limit") or 0) != chapter_count:
            raise ValueError(
                "budget_policy.chapter_limit must equal the frozen chapter coverage"
            )
        if int(budget.get("token_limit") or 0) <= 0:
            raise ValueError("budget_policy.token_limit must be positive")
        try:
            cost_limit = float(budget.get("cost_limit_usd") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("budget_policy.cost_limit_usd must be positive") from exc
        if cost_limit <= 0:
            raise ValueError("budget_policy.cost_limit_usd must be positive")

        text_fields = (
            "campaign_id",
            "protocol_version",
            "evaluation_profile_version",
            "quality_profile_version",
            "reader_outcome_profile_version",
            "project_id",
            "workspace_id",
            "book_id",
        )
        values = {name: _required_text(payload, name) for name in text_fields}
        return cls(
            schema_version=QUALITY_QUALIFICATION_SCHEMA,
            campaign_id=values["campaign_id"],
            campaign_version=campaign_version,
            exact_release_sha=release_sha,
            migration_head=migration_head,
            protocol_version=values["protocol_version"],
            evaluation_profile_version=values["evaluation_profile_version"],
            quality_profile_version=values["quality_profile_version"],
            reader_outcome_profile_version=values["reader_outcome_profile_version"],
            project_id=values["project_id"],
            workspace_id=values["workspace_id"],
            book_id=values["book_id"],
            chapter_group_ranges=ranges,
            required_evaluator_count=required_evaluators,
            _canonical_payload=canonical,
        )

    @property
    def digest(self) -> str:
        return (
            "sha256:"
            + hashlib.sha256(self._canonical_payload.encode("utf-8")).hexdigest()
        )

    def to_dict(self) -> dict[str, Any]:

        return json.loads(self._canonical_payload)

    def allows_chapter(self, chapter_number: int) -> bool:
        return any(
            start <= chapter_number <= end for start, end in self.chapter_group_ranges
        )


_ALLOWED_TRANSITIONS: Mapping[CampaignLifecycle, frozenset[CampaignLifecycle]] = {
    CampaignLifecycle.DRAFT: frozenset(
        {CampaignLifecycle.FROZEN, CampaignLifecycle.ABORTED}
    ),
    CampaignLifecycle.FROZEN: frozenset(
        {CampaignLifecycle.RUNNING, CampaignLifecycle.ABORTED}
    ),
    CampaignLifecycle.RUNNING: frozenset(
        {
            CampaignLifecycle.WAITING_HUMAN_EVIDENCE,
            CampaignLifecycle.EVALUATING,
            CampaignLifecycle.FAILED,
            CampaignLifecycle.ABORTED,
        }
    ),
    CampaignLifecycle.WAITING_HUMAN_EVIDENCE: frozenset(
        {
            CampaignLifecycle.EVALUATING,
            CampaignLifecycle.FAILED,
            CampaignLifecycle.ABORTED,
        }
    ),
    CampaignLifecycle.EVALUATING: frozenset(
        {
            CampaignLifecycle.COMPLETE,
            CampaignLifecycle.WAITING_HUMAN_EVIDENCE,
            CampaignLifecycle.FAILED,
        }
    ),
    CampaignLifecycle.COMPLETE: frozenset(),
    CampaignLifecycle.FAILED: frozenset(),
    CampaignLifecycle.ABORTED: frozenset(),
}


def transition_campaign(
    current: CampaignLifecycle, target: CampaignLifecycle
) -> CampaignLifecycle:
    if not _ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"campaign lifecycle {current.value} is terminal")
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(
            f"campaign cannot transition from {current.value} to {target.value}"
        )
    return target


@dataclass(frozen=True, slots=True)
class QualityEvidence:
    evidence_id: str
    subject_id: str
    layer: EvidenceLayer
    evidence_type: str
    status: EvidenceStatus
    severity: EvidenceSeverity
    source_evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("evidence_id", "subject_id", "evidence_type"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} is required")
        if not self.source_evidence_ids or any(
            not str(item or "").strip() for item in self.source_evidence_ids
        ):
            raise ValueError("source evidence is required")


@dataclass(frozen=True, slots=True)
class QualityQualificationDecision:
    status: QualificationStatus
    lifecycle: CampaignLifecycle
    human_evidence_status: HumanEvidenceStatus
    layer_statuses: Mapping[EvidenceLayer, QualificationStatus]
    limitations: tuple[str, ...]
    diagnostics: tuple[str, ...]
    unproven_claims: tuple[str, ...]


_UNESTABLISHED_EVIDENCE_CLASSES = (
    "STATISTICAL_JUDGE_CALIBRATION",
    "REAL_READER_OUTCOME",
    "LONGITUDINAL_NARRATIVE_STABILITY",
    "PRODUCTION_OPERATION",
    "COMMERCIAL_OUTCOME",
)


def _layer_status(rows: tuple[QualityEvidence, ...]) -> QualificationStatus:
    if not rows:
        return QualificationStatus.NOT_PROVEN
    statuses = {item.status for item in rows}
    if EvidenceStatus.FAIL in statuses:
        return QualificationStatus.FAIL
    if statuses.intersection(
        {
            EvidenceStatus.NOT_PROVEN,
            EvidenceStatus.NOT_OBSERVED,
            EvidenceStatus.WAITING_HUMAN_EVIDENCE,
        }
    ):
        return QualificationStatus.NOT_PROVEN
    if statuses.intersection(
        {EvidenceStatus.PASS_WITH_LIMITATIONS, EvidenceStatus.WARNING}
    ):
        return QualificationStatus.PASS_WITH_LIMITATIONS
    return QualificationStatus.PASS


def decide_quality_qualification(
    evidence: Iterable[QualityEvidence],
    *,
    valid_human_evaluator_ids: Iterable[str],
    human_collection_closed: bool,
    required_evaluator_count: int = 2,
) -> QualityQualificationDecision:

    if required_evaluator_count < 2:
        raise ValueError("required_evaluator_count must be at least two")
    rows = tuple(evidence)
    grouped = {
        layer: tuple(item for item in rows if item.layer is layer)
        for layer in EvidenceLayer
    }
    layer_statuses = {
        layer: _layer_status(layer_rows) for layer, layer_rows in grouped.items()
    }
    diagnostics: list[str] = []
    limitations: list[str] = []
    for layer, layer_rows in grouped.items():
        if not layer_rows:
            diagnostics.append(f"MISSING_{layer.value}")

    severe_l1 = any(
        item.status is EvidenceStatus.FAIL
        and item.severity in {EvidenceSeverity.SEVERE, EvidenceSeverity.BLOCKING}
        for item in grouped[EvidenceLayer.L1_HARD_CORRECTNESS]
    )
    if severe_l1:
        diagnostics.append("SEVERE_L1_FAILURE")

    evaluators = tuple(
        sorted(
            {
                str(item).strip()
                for item in valid_human_evaluator_ids
                if str(item).strip()
            }
        )
    )
    if not evaluators:
        human_status = HumanEvidenceStatus.WAITING_HUMAN_EVIDENCE
        diagnostics.append("HUMAN_BLIND_EVIDENCE_MISSING")
    elif len(evaluators) < required_evaluator_count:
        human_status = HumanEvidenceStatus.HUMAN_EVIDENCE_LIMITED
        limitations.append("ONLY_ONE_VALID_HUMAN_EVALUATOR")
    else:
        human_status = HumanEvidenceStatus.BOUNDED_HUMAN_EVIDENCE

    if any(value is QualificationStatus.FAIL for value in layer_statuses.values()):
        status = QualificationStatus.FAIL
        lifecycle = CampaignLifecycle.FAILED
    elif not evaluators:
        # WHY: Closing collection is meaningful only after at least one valid human
        # evaluation exists. Zero-human campaigns remain explicitly waiting;
        # an operator flag cannot manufacture subjective evidence.
        status = QualificationStatus.NOT_PROVEN
        lifecycle = CampaignLifecycle.WAITING_HUMAN_EVIDENCE
    elif len(evaluators) < required_evaluator_count and not human_collection_closed:
        status = QualificationStatus.NOT_PROVEN
        lifecycle = CampaignLifecycle.WAITING_HUMAN_EVIDENCE
    elif any(
        value is QualificationStatus.NOT_PROVEN for value in layer_statuses.values()
    ):
        status = QualificationStatus.NOT_PROVEN
        lifecycle = CampaignLifecycle.COMPLETE
    elif len(evaluators) < required_evaluator_count:
        status = QualificationStatus.PASS_WITH_LIMITATIONS
        lifecycle = CampaignLifecycle.COMPLETE
    elif any(
        value is QualificationStatus.PASS_WITH_LIMITATIONS
        for value in layer_statuses.values()
    ):
        status = QualificationStatus.PASS_WITH_LIMITATIONS
        lifecycle = CampaignLifecycle.COMPLETE
    else:
        status = QualificationStatus.PASS
        lifecycle = CampaignLifecycle.COMPLETE

    return QualityQualificationDecision(
        status=status,
        lifecycle=lifecycle,
        human_evidence_status=human_status,
        layer_statuses=MappingProxyType(dict(layer_statuses)),
        limitations=tuple(limitations),
        diagnostics=tuple(diagnostics),
        unproven_claims=_UNESTABLISHED_EVIDENCE_CLASSES,
    )


__all__ = [
    "CampaignLifecycle",
    "EvidenceLayer",
    "EvidenceSeverity",
    "EvidenceStatus",
    "HumanEvidenceStatus",
    "QUALITY_QUALIFICATION_SCHEMA",
    "QualityCampaignManifest",
    "QualityEvidence",
    "QualityQualificationDecision",
    "QualificationStatus",
    "decide_quality_qualification",
    "transition_campaign",
]
