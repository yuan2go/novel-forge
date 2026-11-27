"""SECURITY: deconstruction validation never reads Source Blob bytes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError


DECONSTRUCTION_DIMENSIONS = (
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
DOCUMENT_ANALYSIS_DIMENSIONS = (
    "scene_craft",
    "narrative_distance",
    "character_arc",
    "subtext",
    "transition",
    "theme_system",
    "social_pressure",
    "symbol_function",
    "fate_curve",
    "moral_dilemma",
    "craft_principle",
    "core_concept",
    "causal_constraints",
    "credibility_rule",
    "conflict_generator",
    "misuse_risk",
    "review_check",
    "historical_causality",
    "institutional_constraint",
    "social_dynamics",
    "source_reliability",
    "argument_structure",
    "concept_definition",
    "assumption",
    "counterargument",
    "character_choice_cost",
    "information_gap",
    "foreshadowing_payoff",
    "chapter_hook",
    "imagery",
    "emotion_turn",
    "point_of_view",
    "rhythm",
    "concise_expression",
    "scene_atmosphere",
    "value_conflict",
    "historical_context",
    "platform_policy",
    "eligibility_rule",
    "retention_constraint",
    "release_constraint",
    "compliance_risk",
)
SUPPORTED_DECONSTRUCTION_DIMENSIONS = tuple(
    dict.fromkeys((*DECONSTRUCTION_DIMENSIONS, *DOCUMENT_ANALYSIS_DIMENSIONS))
)
DECONSTRUCTION_SCALES = (
    "CHAPTER",
    "CHAPTER_WINDOW",
    "CHAPTER_GROUP",
    "ARC",
    "VOLUME",
    "BOOK",
    "CROSS_BOOK_PATTERN",
    "DOCUMENT_SECTION",
    "LOGICAL_DOCUMENT",
)
FORBIDDEN_OBSERVATION_KEYS = frozenset(
    {
        "raw",
        "raw_content",
        "raw_source",
        "raw_text",
        "clean_text",
        "source_content",
        "source_text",
        "target_text",
        "original_sentence",
        "original_sentences",
        "excerpt",
        "excerpts",
        "quote",
        "quotes",
        "verbatim",
        "content_base64",
    }
)
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTITY = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){0,2}$")


@dataclass(frozen=True, slots=True)
class AnalyzerContract:
    analyzer_id: str
    analyzer_version: str
    dimension: str
    schema_version: str
    prompt_id: str
    prompt_version: str
    skill_id: str
    skill_version: str
    capability_id: str
    capability_version: str
    provider_policy_version: str
    aggregation_policy_version: str
    recommended_scales: tuple[str, ...]
    methodology_content_hash: str = ""

    def __post_init__(self) -> None:
        for value, label in (
            (self.analyzer_id, "analyzer_id"),
            (self.prompt_id, "prompt_id"),
            (self.skill_id, "skill_id"),
            (self.capability_id, "capability_id"),
        ):
            if not _IDENTITY.fullmatch(value):
                raise ValueError(f"{label} is invalid")
        for value, label in (
            (self.analyzer_version, "analyzer_version"),
            (self.prompt_version, "prompt_version"),
            (self.skill_version, "skill_version"),
            (self.capability_version, "capability_version"),
            (self.provider_policy_version, "provider_policy_version"),
            (self.aggregation_policy_version, "aggregation_policy_version"),
        ):
            if not _VERSION.fullmatch(value):
                raise ValueError(f"{label} is invalid")
        if self.dimension not in SUPPORTED_DECONSTRUCTION_DIMENSIONS:
            raise ValueError("deconstruction dimension is invalid")
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*\.v[0-9]+", self.schema_version):
            raise ValueError("observation schema_version is invalid")
        scales = tuple(str(item).strip().upper() for item in self.recommended_scales)
        if not scales or any(item not in DECONSTRUCTION_SCALES for item in scales):
            raise ValueError("recommended deconstruction scale is invalid")
        object.__setattr__(self, "recommended_scales", scales)
        if self.methodology_content_hash and not _SHA256.fullmatch(
            self.methodology_content_hash
        ):
            raise ValueError("methodology_content_hash must be canonical sha256")

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, Any]:
        payload = asdict(self)
        payload["recommended_scales"] = list(self.recommended_scales)
        if not self.methodology_content_hash:
            payload.pop("methodology_content_hash")
        if include_fingerprint:
            payload["fingerprint"] = self.fingerprint
        return payload

    @property
    def fingerprint(self) -> str:
        return stable_hash(self.to_dict(include_fingerprint=False))


@dataclass(frozen=True, slots=True)
class ObservationEvidenceSpan:
    source_chunk_asset_version_id: str
    chunk_byte_start: int
    chunk_byte_end: int
    evidence_hash: str

    def __post_init__(self) -> None:
        if not self.source_chunk_asset_version_id.strip():
            raise ValueError("SourceChunk AssetVersion identity is required")
        if self.chunk_byte_start < 0 or self.chunk_byte_end <= self.chunk_byte_start:
            raise ValueError("Observation evidence span is invalid")
        if not _SHA256.fullmatch(self.evidence_hash):
            raise ValueError("Observation evidence hash must be canonical sha256")

    @property
    def evidence_span_id(self) -> str:
        digest = stable_hash(
            {
                "source_chunk_asset_version_id": self.source_chunk_asset_version_id,
                "chunk_byte_start": self.chunk_byte_start,
                "chunk_byte_end": self.chunk_byte_end,
                "evidence_hash": self.evidence_hash,
            }
        ).removeprefix("sha256:")
        return f"source-evidence-span:{digest}"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "evidence_span_id": self.evidence_span_id}


@dataclass(frozen=True, slots=True)
class ObservationScope:
    scale: str
    range_start: int
    range_end: int
    source_document_ids: tuple[str, ...]
    label: str

    def __post_init__(self) -> None:
        scale = self.scale.strip().upper()
        documents = tuple(
            sorted(
                set(item.strip() for item in self.source_document_ids if item.strip())
            )
        )
        if scale not in DECONSTRUCTION_SCALES:
            raise ValueError("deconstruction scale is invalid")
        if not self.label.strip() or not documents:
            raise ValueError(
                "observation scope label and SourceDocument identities are required"
            )
        if scale == "CROSS_BOOK_PATTERN":
            if len(documents) < 2 or self.range_start != 0 or self.range_end != 0:
                raise ValueError(
                    "cross-book scope requires at least two sources and zero range"
                )
        elif self.range_start <= 0 or self.range_end < self.range_start:
            raise ValueError("observation source range is invalid")
        elif scale == "CHAPTER" and self.range_start != self.range_end:
            raise ValueError("chapter scope must address exactly one chapter")
        object.__setattr__(self, "scale", scale)
        object.__setattr__(self, "source_document_ids", documents)

    @property
    def fingerprint(self) -> str:
        return stable_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "scale": self.scale,
            "range_start": self.range_start,
            "range_end": self.range_end,
            "source_document_ids": list(self.source_document_ids),
            "label": self.label,
        }


@dataclass(frozen=True, slots=True)
class ReprocessingTarget:
    scope: ObservationScope
    analyzer: AnalyzerContract

    def __post_init__(self) -> None:
        if self.scope.scale not in self.analyzer.recommended_scales:
            raise ValueError("analyzer does not support the requested scale")

    @property
    def target_key(self) -> str:
        return stable_hash(
            {
                "scope_fingerprint": self.scope.fingerprint,
                "analyzer_id": self.analyzer.analyzer_id,
                "dimension": self.analyzer.dimension,
            }
        )


def validate_observation_payload(
    payload: Mapping[str, Any],
    *,
    evidence_spans: tuple[ObservationEvidenceSpan, ...] = (),
    input_observation_asset_version_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise KernelError(
            "DECONSTRUCTION_OBSERVATION_INVALID", "observation must be an object"
        )
    observation = dict(payload)
    _assert_source_isolated(observation)
    if len(_canonical_json(observation)) > 512_000:
        raise KernelError(
            "DECONSTRUCTION_OBSERVATION_TOO_LARGE",
            "one dimension Observation exceeds the bounded structured payload",
        )
    findings = observation.get("findings")
    if not isinstance(findings, list) or len(findings) > 500:
        raise KernelError(
            "DECONSTRUCTION_OBSERVATION_INVALID",
            "observation findings must contain at most 500 items",
        )
    if not findings and not str(observation.get("scope_limitations") or "").strip():
        raise KernelError(
            "DECONSTRUCTION_EMPTY_SCOPE_REQUIRED",
            "empty findings require a bounded explanation, not forced knowledge",
        )
    confidence = observation.get("confidence")
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not 0 <= float(confidence) <= 1
    ):
        raise KernelError(
            "DECONSTRUCTION_CONFIDENCE_INVALID",
            "observation confidence must be within [0, 1]",
        )
    if str(observation.get("knowledge_status") or "") != "NOT_ABSTRACTED":
        raise KernelError(
            "DECONSTRUCTION_KNOWLEDGE_BOUNDARY_INVALID",
            "Observation must declare knowledge_status=NOT_ABSTRACTED",
        )
    allowed_evidence = {span.evidence_span_id for span in evidence_spans}
    allowed_inputs = {
        item for item in input_observation_asset_version_ids if item.strip()
    }
    if not allowed_evidence and not allowed_inputs:
        raise KernelError(
            "DECONSTRUCTION_LINEAGE_REQUIRED",
            "Observation requires EvidenceSpan or lower-scale Observation lineage",
        )
    for finding in findings:
        if not isinstance(finding, Mapping):
            raise KernelError(
                "DECONSTRUCTION_OBSERVATION_INVALID", "each finding must be an object"
            )
        if (
            not str(finding.get("finding_code") or "").strip()
            or not str(finding.get("statement") or "").strip()
        ):
            raise KernelError(
                "DECONSTRUCTION_OBSERVATION_INVALID",
                "each finding requires finding_code and statement",
            )
        refs = {
            str(item)
            for item in finding.get("evidence_span_ids") or []
            if str(item).strip()
        }
        observation_refs = {
            str(item)
            for item in finding.get("input_observation_asset_version_ids") or []
            if str(item).strip()
        }
        if not refs and not observation_refs:
            raise KernelError(
                "DECONSTRUCTION_FINDING_EVIDENCE_REQUIRED",
                "each finding requires evidence or lower-scale Observation refs",
            )
        if not refs.issubset(allowed_evidence) or not observation_refs.issubset(
            allowed_inputs
        ):
            raise KernelError(
                "DECONSTRUCTION_FINDING_EVIDENCE_UNKNOWN",
                "finding references evidence outside the frozen input set",
            )
    return observation


def validate_evidence_spans(
    spans: tuple[ObservationEvidenceSpan, ...],
    *,
    source_chunk_sizes: Mapping[str, int],
) -> tuple[ObservationEvidenceSpan, ...]:
    ordered = tuple(
        sorted(
            spans,
            key=lambda item: (
                item.source_chunk_asset_version_id,
                item.chunk_byte_start,
                item.chunk_byte_end,
                item.evidence_hash,
            ),
        )
    )
    identities: set[str] = set()
    for span in ordered:
        size = source_chunk_sizes.get(span.source_chunk_asset_version_id)
        if size is None:
            raise KernelError(
                "DECONSTRUCTION_SOURCE_CHUNK_NOT_FOUND",
                "Observation EvidenceSpan references an unavailable SourceChunk version",
            )
        if span.chunk_byte_end > int(size):
            raise KernelError(
                "DECONSTRUCTION_EVIDENCE_OUT_OF_BOUNDS",
                "Observation EvidenceSpan exceeds its frozen SourceChunk",
            )
        if span.evidence_span_id in identities:
            raise KernelError(
                "DECONSTRUCTION_EVIDENCE_DUPLICATE",
                "Observation EvidenceSpan identities must be unique",
            )
        identities.add(span.evidence_span_id)
    return ordered


def analyzer_prompt_bundle(contract: AnalyzerContract) -> dict[str, Any]:
    return {
        "prompt_id": contract.prompt_id,
        "prompt_version": contract.prompt_version,
        "analyzer_id": contract.analyzer_id,
        "analyzer_version": contract.analyzer_version,
        "dimension": contract.dimension,
        "output_kind": "OBSERVATION",
        "instruction": (
            f"Analyze only the {contract.dimension} dimension for the requested scale. "
            "Record what the governed evidence supports, cite stable evidence_span_ids, "
            "separate uncertainty from findings, and do not emit reusable story knowledge."
        ),
        "required_fields": [
            "findings",
            "finding_code",
            "statement",
            "evidence_span_ids",
            "confidence",
            "originality_risk",
            "knowledge_status=NOT_ABSTRACTED",
        ],
        "source_policy": {
            "raw_source_output_forbidden": True,
            "protected_expression_output_forbidden": True,
            "whole_book_single_call_forbidden": True,
            "aggregation_prefers_observations_over_source": True,
            "generation_context_allowed": False,
        },
        "schema_version": contract.schema_version,
        "contract_fingerprint": contract.fingerprint,
    }


def default_analyzer_contracts() -> dict[str, AnalyzerContract]:
    scale_map = {
        "structure": ("CHAPTER_GROUP", "ARC", "VOLUME", "BOOK", "CROSS_BOOK_PATTERN"),
        "pacing": (
            "CHAPTER",
            "CHAPTER_WINDOW",
            "CHAPTER_GROUP",
            "ARC",
            "VOLUME",
            "BOOK",
            "CROSS_BOOK_PATTERN",
        ),
        "hook": (
            "CHAPTER",
            "CHAPTER_WINDOW",
            "CHAPTER_GROUP",
            "ARC",
            "VOLUME",
            "BOOK",
            "CROSS_BOOK_PATTERN",
        ),
        "reward_payoff": (
            "CHAPTER",
            "CHAPTER_WINDOW",
            "CHAPTER_GROUP",
            "ARC",
            "VOLUME",
            "BOOK",
            "CROSS_BOOK_PATTERN",
        ),
        "reader_promise": (
            "CHAPTER",
            "CHAPTER_WINDOW",
            "CHAPTER_GROUP",
            "ARC",
            "VOLUME",
            "BOOK",
            "CROSS_BOOK_PATTERN",
        ),
        "conflict": (
            "CHAPTER",
            "CHAPTER_WINDOW",
            "CHAPTER_GROUP",
            "ARC",
            "VOLUME",
            "BOOK",
            "CROSS_BOOK_PATTERN",
        ),
        "character_mechanism": (
            "CHAPTER_WINDOW",
            "CHAPTER_GROUP",
            "ARC",
            "VOLUME",
            "BOOK",
            "CROSS_BOOK_PATTERN",
        ),
        "relationship_mechanism": (
            "CHAPTER_WINDOW",
            "CHAPTER_GROUP",
            "ARC",
            "VOLUME",
            "BOOK",
            "CROSS_BOOK_PATTERN",
        ),
        "emotion_curve": (
            "CHAPTER",
            "CHAPTER_WINDOW",
            "CHAPTER_GROUP",
            "ARC",
            "VOLUME",
            "BOOK",
            "CROSS_BOOK_PATTERN",
        ),
        "foreshadowing": (
            "CHAPTER",
            "CHAPTER_WINDOW",
            "CHAPTER_GROUP",
            "ARC",
            "VOLUME",
            "BOOK",
            "CROSS_BOOK_PATTERN",
        ),
        "information_progression": (
            "CHAPTER",
            "CHAPTER_WINDOW",
            "CHAPTER_GROUP",
            "ARC",
            "VOLUME",
            "BOOK",
            "CROSS_BOOK_PATTERN",
        ),
        "serialization": (
            "CHAPTER_WINDOW",
            "CHAPTER_GROUP",
            "ARC",
            "VOLUME",
            "BOOK",
            "CROSS_BOOK_PATTERN",
        ),
        "commercial_logic": (
            "CHAPTER_WINDOW",
            "CHAPTER_GROUP",
            "ARC",
            "VOLUME",
            "BOOK",
            "CROSS_BOOK_PATTERN",
        ),
        "originality_copyright_risk": (
            "CHAPTER_WINDOW",
            "CHAPTER_GROUP",
            "ARC",
            "VOLUME",
            "BOOK",
            "CROSS_BOOK_PATTERN",
        ),
    }
    return {
        dimension: AnalyzerContract(
            analyzer_id=f"hot-novel.{dimension}",
            analyzer_version="1.0.0",
            dimension=dimension,
            schema_version="source-deconstruction-observation.v1",
            prompt_id=f"hot-novel.{dimension}.observation",
            prompt_version="1.0.0",
            skill_id="hot-novel-deconstruction",
            skill_version="2.0.0",
            capability_id="deconstruction.observe",
            capability_version="1.0.0",
            provider_policy_version="1.0.0",
            aggregation_policy_version="1.0.0",
            recommended_scales=scales,
        )
        for dimension, scales in scale_map.items()
    }


def stable_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _assert_source_isolated(value: Any, *, path: str = "observation") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            if normalized in FORBIDDEN_OBSERVATION_KEYS:
                raise KernelError(
                    "DECONSTRUCTION_SOURCE_LEAKAGE_BLOCKED",
                    f"forbidden source-expression field at {path}.{key}",
                )
            _assert_source_isolated(nested, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _assert_source_isolated(nested, path=f"{path}[{index}]")


__all__ = [
    "DECONSTRUCTION_DIMENSIONS",
    "DOCUMENT_ANALYSIS_DIMENSIONS",
    "DECONSTRUCTION_SCALES",
    "AnalyzerContract",
    "ObservationEvidenceSpan",
    "ObservationScope",
    "ReprocessingTarget",
    "SUPPORTED_DECONSTRUCTION_DIMENSIONS",
    "analyzer_prompt_bundle",
    "default_analyzer_contracts",
    "stable_hash",
    "validate_evidence_spans",
    "validate_observation_payload",
]
