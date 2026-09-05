from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from typing import Any, Mapping


REPORT_SCHEMA = "novel-forge.narrative-qualification.v1"
BLIND_SCHEMA = "novel-forge.narrative-editorial-pack.v1"
DIMENSIONS = (
    "engineering",
    "narrative_correctness",
    "human_editorial",
    "reader_evidence",
    "longitudinal_stability",
    "production_evidence",
)
DIMENSION_STATUSES = {
    "engineering": {"QUALIFIED", "NOT_PROVEN"},
    "narrative_correctness": {"BOUNDED_CONTRACT_EVIDENCE", "NOT_PROVEN"},
    "human_editorial": {"BOUNDED_HUMAN_EVIDENCE", "WAITING_EVIDENCE"},
    "reader_evidence": {"NOT_PROVEN"},
    "longitudinal_stability": {"EVIDENCE_NOT_YET_SUFFICIENT"},
    "production_evidence": {"NOT_PROVEN"},
}


@dataclass(frozen=True, slots=True)
class EvidenceDimension:
    status: str
    proof_ceiling: str
    evidence_refs: tuple[str, ...]
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.proof_ceiling or not self.limitations:
            raise ValueError(
                "an evidence dimension requires its ceiling and limitations"
            )
        if (
            self.status
            in {"QUALIFIED", "BOUNDED_CONTRACT_EVIDENCE", "BOUNDED_HUMAN_EVIDENCE"}
            and not self.evidence_refs
        ):
            raise ValueError("positive evidence requires exact source references")


@dataclass(frozen=True, slots=True)
class NarrativeQualificationReport:
    implementation: Mapping[str, Any]
    source: Mapping[str, Any]
    sampling: Mapping[str, Any]
    dimensions: Mapping[str, EvidenceDimension]
    accepted_chapters: tuple[dict[str, Any], ...]
    design_evidence: Mapping[str, Any]
    progress_observations: tuple[dict[str, Any], ...]
    longitudinal_observations: Mapping[str, Any]
    real_chapter_production: Mapping[str, Any]
    blind_pack: Mapping[str, Any]
    limitations: tuple[str, ...]
    schema_version: str = REPORT_SCHEMA
    collection_status: str = "PASS"

    def __post_init__(self) -> None:
        if self.schema_version != REPORT_SCHEMA or self.collection_status != "PASS":
            raise ValueError("invalid narrative evidence collection contract")
        if set(self.dimensions) != set(DIMENSIONS):
            raise ValueError(
                "qualification requires exactly six independent dimensions"
            )
        if not re.fullmatch(
            r"[0-9a-f]{40}", str(self.implementation.get("commit_sha") or "")
        ):
            raise ValueError("qualification requires exact source SHA")
        if not re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            str(self.implementation.get("implementation_tree_sha") or ""),
        ):
            raise ValueError("qualification requires exact implementation identity")
        for name, dimension in self.dimensions.items():
            if dimension.status not in DIMENSION_STATUSES[name]:
                raise ValueError(f"unsupported qualification dimension status: {name}")
        if self.source.get("fixture_backed") is True:
            for name in ("narrative_correctness", "human_editorial"):
                if self.dimensions[name].status not in {
                    "NOT_PROVEN",
                    "WAITING_EVIDENCE",
                }:
                    raise ValueError(
                        "fixture evidence cannot qualify narrative or human quality"
                    )
            if self.real_chapter_production.get("status") != "NOT_PROVEN":
                raise ValueError(
                    "fixture evidence cannot qualify real chapter production"
                )

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), ensure_ascii=False, allow_nan=False))


@dataclass(frozen=True, slots=True)
class BlindEditorialSample:
    sample_token: str
    sequence_position: int
    text: str

    def __post_init__(self) -> None:
        if (
            not self.sample_token
            or self.sequence_position <= 0
            or not self.text.strip()
        ):
            raise ValueError("blind editorial sample requires text and sequence")


@dataclass(frozen=True, slots=True)
class BlindEditorialPack:
    pack_token: str
    rubric_dimensions: tuple[str, ...]
    samples: tuple[BlindEditorialSample, ...]
    schema_version: str = BLIND_SCHEMA
    review_mode: str = "SINGLE_ARM_EDITORIAL"
    instruction: str = "Read the supplied sequence independently. Record findings with sample tokens and text spans; no evaluation has been submitted by this pack."

    def to_dict(self) -> dict[str, Any]:
        if (
            self.schema_version != BLIND_SCHEMA
            or not self.pack_token
            or not self.rubric_dimensions
        ):
            raise ValueError("blind editorial pack identity and rubric are required")
        return json.loads(json.dumps(asdict(self), ensure_ascii=False))
