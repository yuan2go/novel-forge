"""Pure Source profiling, logical-document and classification admission contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Iterable, Mapping


_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_VERSION = re.compile(r"^[a-z][a-z0-9_.-]+\.v[0-9]+$")

SOURCE_CLASSIFIER_METHODOLOGY = """Classify one governed LogicalDocument from deterministic metadata, structural signals, generic path hints, and bounded semantic samples. Treat path as weak evidence only. Select exactly one governed taxonomy type, report calibrated alternatives and evidence codes, and flag suspected multi-document or mixed boundaries. Return UNKNOWN or MIXED when evidence is insufficient or composite; never force a routable type and never quote source expression."""
SOURCE_CLASSIFIER_METHODOLOGY_HASH = (
    "sha256:"
    + hashlib.sha256(SOURCE_CLASSIFIER_METHODOLOGY.encode("utf-8")).hexdigest()
)


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class SourceContentType(StrEnum):
    WEB_NOVEL = "WEB_NOVEL"
    PUBLISHED_FICTION = "PUBLISHED_FICTION"
    CLASSIC_LITERATURE = "CLASSIC_LITERATURE"
    WRITING_THEORY = "WRITING_THEORY"
    PROFESSIONAL_KNOWLEDGE = "PROFESSIONAL_KNOWLEDGE"
    HISTORY_SOCIAL_SCIENCE = "HISTORY_SOCIAL_SCIENCE"
    BIOGRAPHY_MEMOIR = "BIOGRAPHY_MEMOIR"
    PHILOSOPHY_ESSAY = "PHILOSOPHY_ESSAY"
    PLATFORM_RULES = "PLATFORM_RULES"
    UNKNOWN = "UNKNOWN"
    MIXED = "MIXED"


@dataclass(frozen=True, slots=True)
class SourceIntelligencePolicy:
    policy_version: str = "source-intelligence-policy.v1"
    classifier_id: str = "novel-forge.source-content-classifier"
    classifier_version: str = "1.0"
    classifier_prompt_version: str = "1.0"
    classifier_schema_version: str = "source-content-classification.v1"
    classifier_capability: str = "source.content.classify"
    signal_schema_version: str = "source-profile-signals.v1"
    sample_policy_version: str = "source-profile-sampling.v1"
    routing_policy_version: str = "source-analysis-routing.v2"
    logical_document_policy_version: str = "file-logical-document.v1"
    min_confidence: float = 0.72
    min_margin: float = 0.12
    max_sample_chunks: int = 3
    max_sample_bytes_per_chunk: int = 6_000
    max_signal_bytes: int = 128_000

    def __post_init__(self) -> None:
        for value, label in (
            (self.policy_version, "policy_version"),
            (self.signal_schema_version, "signal_schema_version"),
            (self.sample_policy_version, "sample_policy_version"),
            (self.routing_policy_version, "routing_policy_version"),
            (self.logical_document_policy_version, "logical_document_policy_version"),
        ):
            if not _VERSION.fullmatch(value):
                raise ValueError(f"Source intelligence {label} is invalid")
        if not all(
            value.strip()
            for value in (
                self.classifier_id,
                self.classifier_version,
                self.classifier_prompt_version,
                self.classifier_schema_version,
                self.classifier_capability,
            )
        ):
            raise ValueError("Source intelligence classifier contract is incomplete")
        if not 0 < self.min_confidence <= 1 or not 0 <= self.min_margin <= 1:
            raise ValueError("Source intelligence confidence policy is invalid")
        if (
            min(
                self.max_sample_chunks,
                self.max_sample_bytes_per_chunk,
                self.max_signal_bytes,
            )
            <= 0
        ):
            raise ValueError("Source intelligence sampling limits must be positive")

    @property
    def classifier_contract_hash(self) -> str:
        return canonical_hash(self.classifier_contract)

    @property
    def classifier_contract(self) -> dict[str, str]:
        return {
            "classifier_id": self.classifier_id,
            "classifier_version": self.classifier_version,
            "prompt_version": self.classifier_prompt_version,
            "schema_version": self.classifier_schema_version,
            "capability": self.classifier_capability,
            "signal_schema_version": self.signal_schema_version,
            "sample_policy_version": self.sample_policy_version,
            "logical_document_policy_version": self.logical_document_policy_version,
            "methodology_version": "source-content-classifier-methodology.v1",
            "methodology_content_hash": SOURCE_CLASSIFIER_METHODOLOGY_HASH,
        }

    @property
    def policy_hash(self) -> str:
        return canonical_hash(asdict(self))


@dataclass(frozen=True, slots=True)
class SourceAnalysisOverride:
    logical_document_scope_hash: str
    content_type: SourceContentType
    reason: str
    decision_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "content_type", SourceContentType(self.content_type))
        if not _SHA256.fullmatch(self.logical_document_scope_hash):
            raise ValueError(
                "governance override requires a LogicalDocument scope hash"
            )
        if self.content_type in {SourceContentType.UNKNOWN, SourceContentType.MIXED}:
            raise ValueError("governance override requires a routable content type")
        if len(self.reason.strip()) < 20 or not self.decision_ref.strip():
            raise ValueError(
                "governance override requires a substantive reason and decision ref"
            )

    @property
    def contract_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, str]:
        return {
            "logical_document_scope_hash": self.logical_document_scope_hash,
            "content_type": self.content_type.value,
            "reason": self.reason.strip(),
            "decision_ref": self.decision_ref.strip(),
        }


@dataclass(frozen=True, slots=True)
class LogicalDocumentScope:
    scope_kind: str
    source_document_id: str
    source_transform_id: str
    source_chunk_asset_version_ids: tuple[str, ...]
    boundary_policy_version: str
    label: str

    def __post_init__(self) -> None:
        if self.scope_kind != "FILE_DOCUMENT":
            raise ValueError("only FILE_DOCUMENT boundary resolution is implemented")
        if (
            not all(
                value.strip()
                for value in (
                    self.source_document_id,
                    self.source_transform_id,
                    self.boundary_policy_version,
                    self.label,
                )
            )
            or not self.source_chunk_asset_version_ids
        ):
            raise ValueError("LogicalDocument scope is incomplete")
        chunks = tuple(dict.fromkeys(self.source_chunk_asset_version_ids))
        if len(chunks) != len(self.source_chunk_asset_version_ids) or any(
            not item.strip() for item in chunks
        ):
            raise ValueError("LogicalDocument chunks must be non-empty and unique")
        object.__setattr__(self, "source_chunk_asset_version_ids", chunks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope_kind": self.scope_kind,
            "source_document_id": self.source_document_id,
            "source_transform_id": self.source_transform_id,
            "source_chunk_asset_version_ids": list(self.source_chunk_asset_version_ids),
            "boundary_policy_version": self.boundary_policy_version,
            "label": self.label,
        }

    @property
    def scope_hash(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True, slots=True)
class ClassificationSample:
    source_chunk_asset_version_id: str
    byte_start: int
    byte_end: int
    sample_hash: str
    position: str

    def __post_init__(self) -> None:
        if (
            not self.source_chunk_asset_version_id.strip()
            or self.byte_start < 0
            or self.byte_end <= self.byte_start
            or not _SHA256.fullmatch(self.sample_hash)
            or self.position not in {"BEGINNING", "MIDDLE", "END"}
        ):
            raise ValueError("classification sample identity is invalid")

    @property
    def sample_id(self) -> str:
        return "source-classification-sample:" + canonical_hash(
            asdict(self)
        ).removeprefix("sha256:")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "sample_id": self.sample_id}


@dataclass(frozen=True, slots=True)
class ClassificationEvidence:
    logical_document_scope_hash: str
    signals: dict[str, Any]
    path_hints: tuple[str, ...]
    samples: tuple[ClassificationSample, ...]
    signal_schema_version: str
    sample_policy_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_document_scope_hash": self.logical_document_scope_hash,
            "signals": self.signals,
            "path_hints": list(self.path_hints),
            "samples": [item.to_dict() for item in self.samples],
            "signal_schema_version": self.signal_schema_version,
            "sample_policy_version": self.sample_policy_version,
        }

    @property
    def input_hash(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True, slots=True)
class SourceProfileResolution:
    predicted_content_type: SourceContentType
    resolved_content_type: SourceContentType
    confidence: float
    margin: float
    status: str
    manual_review_required: bool
    resolution_mode: str
    reasons: tuple[str, ...]
    override_decision_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["predicted_content_type"] = self.predicted_content_type.value
        payload["resolved_content_type"] = self.resolved_content_type.value
        payload["reasons"] = list(self.reasons)
        return payload


def build_classification_evidence(
    *,
    scope: LogicalDocumentScope,
    path_hints: Iterable[str],
    source_segments: tuple[dict[str, Any], ...],
    policy: SourceIntelligencePolicy,
) -> ClassificationEvidence:
    by_id = {
        str(item.get("source_chunk_asset_version_id") or ""): item
        for item in source_segments
    }
    if set(by_id) != set(scope.source_chunk_asset_version_ids):
        raise ValueError("classification segments differ from LogicalDocument scope")
    ordered = [by_id[item] for item in scope.source_chunk_asset_version_ids]
    for item in ordered:
        content = str(item.get("content") or "").encode("utf-8")
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        if digest != str(item.get("content_hash") or "") or len(content) != int(
            item.get("byte_size") or -1
        ):
            raise ValueError("classification SourceChunk identity drifted")
    indexes = _stratified_indexes(len(ordered), policy.max_sample_chunks)
    samples: list[ClassificationSample] = []
    signal_parts: list[str] = []
    remaining_signal_bytes = policy.max_signal_bytes
    for index, item in enumerate(ordered):
        text = str(item["content"])
        encoded = text.encode("utf-8")
        if remaining_signal_bytes:
            bounded = encoded[:remaining_signal_bytes]
            bounded = _valid_utf8_prefix(bounded)
            signal_parts.append(bounded.decode("utf-8"))
            remaining_signal_bytes -= len(bounded)
        if index not in indexes:
            continue
        sample_bytes = _valid_utf8_prefix(encoded[: policy.max_sample_bytes_per_chunk])
        position = (
            "BEGINNING"
            if index == indexes[0]
            else "END"
            if index == indexes[-1] and len(indexes) > 1
            else "MIDDLE"
        )
        samples.append(
            ClassificationSample(
                source_chunk_asset_version_id=str(
                    item["source_chunk_asset_version_id"]
                ),
                byte_start=0,
                byte_end=len(sample_bytes),
                sample_hash="sha256:" + hashlib.sha256(sample_bytes).hexdigest(),
                position=position,
            )
        )
    combined = "\n".join(signal_parts)
    signals = _content_signals(combined)
    signals.update(
        {
            "chunk_count": len(ordered),
            "total_bytes": sum(int(item["byte_size"]) for item in ordered),
            "sample_count": len(samples),
        }
    )
    return ClassificationEvidence(
        logical_document_scope_hash=scope.scope_hash,
        signals=signals,
        path_hints=_path_tokens(path_hints),
        samples=tuple(samples),
        signal_schema_version=policy.signal_schema_version,
        sample_policy_version=policy.sample_policy_version,
    )


def resolve_profile(
    *,
    classifier_output: Mapping[str, Any],
    policy: SourceIntelligencePolicy,
    override: SourceAnalysisOverride | None = None,
) -> SourceProfileResolution:
    try:
        predicted = SourceContentType(str(classifier_output["content_type"]))
        confidence = float(classifier_output["confidence"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "classifier output has an invalid content type/confidence"
        ) from exc
    alternatives = classifier_output.get("alternatives")
    boundary = classifier_output.get("boundary_assessment")
    if (
        not 0 <= confidence <= 1
        or not isinstance(alternatives, list)
        or not alternatives
        or not isinstance(boundary, Mapping)
    ):
        raise ValueError("classifier output is incomplete")
    scores: dict[SourceContentType, float] = {}
    for item in alternatives:
        if not isinstance(item, Mapping):
            raise ValueError("classifier alternative must be an object")
        try:
            kind = SourceContentType(str(item["content_type"]))
            score = float(item["confidence"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("classifier alternative is invalid") from exc
        if not 0 <= score <= 1 or kind in scores:
            raise ValueError("classifier alternatives must be unique probabilities")
        scores[kind] = score
    if scores.get(predicted) != confidence:
        raise ValueError("classifier top result differs from its alternatives")
    other = max(
        (score for kind, score in scores.items() if kind != predicted), default=0
    )
    margin = confidence - other
    reasons: list[str] = []
    if predicted in {SourceContentType.UNKNOWN, SourceContentType.MIXED}:
        reasons.append("UNROUTABLE_CONTENT_TYPE")
    if confidence < policy.min_confidence:
        reasons.append("LOW_CONFIDENCE")
    if margin < policy.min_margin:
        reasons.append("LOW_CLASSIFICATION_MARGIN")
    if (
        bool(boundary.get("review_required"))
        or int(boundary.get("suspected_document_count") or 0) != 1
    ):
        reasons.append("LOGICAL_DOCUMENT_BOUNDARY_REVIEW_REQUIRED")
    if override is not None:
        if "LOGICAL_DOCUMENT_BOUNDARY_REVIEW_REQUIRED" in reasons:
            return SourceProfileResolution(
                predicted_content_type=predicted,
                resolved_content_type=SourceContentType.UNKNOWN,
                confidence=confidence,
                margin=margin,
                status="NEEDS_REVIEW",
                manual_review_required=True,
                resolution_mode="GOVERNANCE_OVERRIDE",
                reasons=tuple(reasons),
                override_decision_ref=override.decision_ref,
            )
        return SourceProfileResolution(
            predicted_content_type=predicted,
            resolved_content_type=override.content_type,
            confidence=confidence,
            margin=margin,
            status="ROUTABLE",
            manual_review_required=False,
            resolution_mode="GOVERNANCE_OVERRIDE",
            reasons=tuple(reasons),
            override_decision_ref=override.decision_ref,
        )
    routable = not reasons
    return SourceProfileResolution(
        predicted_content_type=predicted,
        resolved_content_type=(predicted if routable else SourceContentType.UNKNOWN),
        confidence=confidence,
        margin=margin,
        status="ROUTABLE" if routable else "NEEDS_REVIEW",
        manual_review_required=not routable,
        resolution_mode="AUTOMATIC",
        reasons=tuple(reasons),
    )


def _stratified_indexes(count: int, limit: int) -> tuple[int, ...]:
    if count <= 0:
        raise ValueError("classification requires at least one SourceChunk")
    if count <= limit:
        return tuple(range(count))
    candidates = (0, count // 2, count - 1)
    return tuple(dict.fromkeys(candidates[:limit]))


def _valid_utf8_prefix(value: bytes) -> bytes:
    while value:
        try:
            value.decode("utf-8", errors="strict")
            return value
        except UnicodeDecodeError:
            value = value[:-1]
    raise ValueError("classification sample is empty")


def _path_tokens(paths: Iterable[str]) -> tuple[str, ...]:
    tokens: list[str] = []
    for path in paths:
        tokens.extend(
            item.lower() for item in re.findall(r"[A-Za-z0-9\u3400-\u9fff]+", str(path))
        )
    return tuple(dict.fromkeys(tokens))


def _content_signals(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    nonempty = [line for line in lines if line.strip()]
    paragraphs = [item for item in re.split(r"\n\s*\n", text) if item.strip()]
    headings = [
        line
        for line in nonempty
        if re.match(
            r"^\s*(?:#{1,6}\s+|第[零一二三四五六七八九十百千万0-9]+[章节卷部回])",
            line,
        )
    ]
    dialogue = [line for line in nonempty if re.match(r'^\s*[“"「『—-]', line)]
    citations = re.findall(
        r"(?:\[[0-9]+\]|\([A-Z][A-Za-z-]+,?\s+[12][0-9]{3}\)|doi:|https?://)",
        text,
        flags=re.IGNORECASE,
    )
    list_lines = [
        line for line in nonempty if re.match(r"^\s*(?:[-*+] |\d+[.)]\s+)", line)
    ]
    years = re.findall(r"(?<!\d)(?:1[5-9]\d{2}|20\d{2})(?!\d)", text)
    first_person = re.findall(
        r"\b(?:I|me|my|mine|we|our|ours)\b|我|我们|本人|笔者",
        text,
        flags=re.IGNORECASE,
    )
    sentences = max(1, len(re.findall(r"[.!?。！？]+", text)))
    return {
        "character_count": len(text),
        "line_count": len(lines),
        "paragraph_count": len(paragraphs),
        "heading_count": len(headings),
        "dialogue_line_ratio": round(len(dialogue) / max(1, len(nonempty)), 6),
        "citation_count": len(citations),
        "list_line_ratio": round(len(list_lines) / max(1, len(nonempty)), 6),
        "year_reference_count": len(years),
        "first_person_density": round(len(first_person) / sentences, 6),
        "average_paragraph_characters": round(
            sum(len(item) for item in paragraphs) / max(1, len(paragraphs)), 3
        ),
        "table_like_line_count": sum(line.count("|") >= 2 for line in nonempty),
        "chapter_marker_count": len(
            re.findall(
                r"第[零一二三四五六七八九十百千万0-9]+[章节卷部回]",
                text,
            )
        ),
    }


__all__ = [
    "ClassificationEvidence",
    "ClassificationSample",
    "LogicalDocumentScope",
    "SourceAnalysisOverride",
    "SourceContentType",
    "SourceIntelligencePolicy",
    "SourceProfileResolution",
    "SOURCE_CLASSIFIER_METHODOLOGY",
    "SOURCE_CLASSIFIER_METHODOLOGY_HASH",
    "build_classification_evidence",
    "canonical_hash",
    "resolve_profile",
]
