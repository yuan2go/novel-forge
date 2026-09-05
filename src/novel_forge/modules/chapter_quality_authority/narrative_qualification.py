from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from novel_forge.modules.chapter_authority.provider_output_contracts import (
    validate_chapter_provider_output_against_schema,
)


NARRATIVE_REPORT_SCHEMA = "novel-forge.narrative-qualification.v1"
NARRATIVE_LAYERS = (
    "INTENT",
    "FOUNDATION",
    "BOOK_ARCHITECTURE",
    "TRAJECTORY_PORTFOLIO",
    "CHAPTER_MISSION",
    "SCENE_ARCHITECTURE",
    "PROSE",
    "ACCEPTANCE",
    "LONGITUDINAL_NARRATIVE",
)
NARRATIVE_EVIDENCE_DIMENSIONS = (
    "ENGINEERING",
    "NARRATIVE_CORRECTNESS",
    "HUMAN_EDITORIAL",
    "READER_EVIDENCE",
    "LONGITUDINAL_STABILITY",
    "PRODUCTION_EVIDENCE",
)
NARRATIVE_LAYER_CONTRACTS = {
    "INTENT": (
        "StoryDesign candidate + topic inputs",
        "qualified creative/theme/ending/reader-promise AssetVersions",
        "StoryDesignAssetAuthority",
        "required_qualification_profiles: STORY_INTENT",
    ),
    "FOUNDATION": (
        "qualified Intent + WorldBible/CharacterCast candidates",
        "ready immutable FoundationSet",
        "BookDesignAuthority + StoryDesignAssetAuthority",
        "require_current_foundation_set(require_ready=True)",
    ),
    "BOOK_ARCHITECTURE": (
        "ready FoundationSet + active BookDesign",
        "active typed BookPlan",
        "HierarchicalPlanningAuthority",
        "BookPlan foundation identity + BOOK_ARCHITECTURE/CHARACTER_DEVELOPMENT/DISCLOSURE_OBLIGATION receipts",
    ),
    "TRAJECTORY_PORTFOLIO": (
        "active BookPlan + ArcPlan/character development",
        "DESIGN_REVIEW_REQUIRED: typed relationship/thematic trajectory portfolio",
        "DESIGN_REVIEW_REQUIRED: existing Arc/Character owners do not define full portfolio lifecycle",
        "DESIGN_REVIEW_REQUIRED",
    ),
    "CHAPTER_MISSION": (
        "frozen ChapterGroup schedule + ArcWorkingSet + NarrativeRealization",
        "active ChapterPlan: chapter-mission-scene.v2",
        "HierarchicalPlanningAuthority",
        "CHAPTER_MISSION semantic receipt + require_chapter_contracts",
    ),
    "SCENE_ARCHITECTURE": (
        "same immutable ChapterPlan Mission commitments",
        "typed scene_plan + ordered Beat references",
        "HierarchicalPlanningAuthority",
        "SCENE_ARCHITECTURE semantic receipt + validate_scene_mission_coverage",
    ),
    "PROSE": (
        "active ChapterPlan + governed Context + ExecutionIntent",
        "draft/revision candidates + review/quality evidence",
        "ChapterAuthority",
        "Review/Revision/Quality gates; Provider output remains candidate",
    ),
    "ACCEPTANCE": (
        "qualified ChapterOutcome + Canon/NarrativeState projections",
        "committed Accepted Actual",
        "BookProductionAuthority",
        "authority_book_chapter_acceptance COMMITTED + successful native acceptance Operation",
    ),
    "LONGITUDINAL_NARRATIVE": (
        "accepted temporal history + independent Reader/Human evidence",
        "bounded longitudinal observations",
        "ChapterQualityAuthority (evidence projection only)",
        "independent longitudinal evidence required; sample count is not a gate",
    ),
}
_GENERATORS_BY_LAYER = {
    "INTENT": {
        "creative.candidates.generate",
        "theme.candidates.generate",
        "ending.intent.generate",
        "reader.promise.generate",
    },
    "FOUNDATION": {"world.design.generate", "character.cast.generate"},
    "BOOK_ARCHITECTURE": {"book_plan.generate"},
    "TRAJECTORY_PORTFOLIO": {"arc_plan.generate"},
    "CHAPTER_MISSION": {"chapter_plan.generate"},
    "SCENE_ARCHITECTURE": {"chapter_plan.generate"},
}
_STATUSES = [
    "PASS",
    "FAIL",
    "NOT_PROVEN",
    "SUPPORTING_ONLY",
    "WAITING_EVIDENCE",
    "DESIGN_REVIEW_REQUIRED",
    "BLOCKED_BY_UPSTREAM",
]


def narrative_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class NarrativeReceipt:
    receipt_id: str
    source_table: str
    layer: str
    generator: str
    asset_version_id: str
    content_hash: str
    operation_id: str
    implementation_sha: str
    generation_sha: str
    source_class: str
    status: str
    current: bool
    native_lineage_valid: bool
    profile_current: bool
    chapter_number: int = 0
    gate_status: str = "PASS"
    gate_reason: str = ""


def _object(properties: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(properties),
        "additionalProperties": False,
    }


_TEXT = {"type": "string"}
_TEXTS = {"type": "array", "items": _TEXT}
_STATUS = {"type": "string", "enum": _STATUSES}
NARRATIVE_QUALIFICATION_REPORT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    **_object(
        {
            "schema_version": {"const": NARRATIVE_REPORT_SCHEMA},
            "project_id": _TEXT,
            "book_id": _TEXT,
            "implementation_sha": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
            "implementation_tree_sha": {
                "type": "string",
                "pattern": "^sha256:[0-9a-f]{64}$",
            },
            "input_digest": _TEXT,
            "report_digest": _TEXT,
            "status": _STATUS,
            "layers": {
                "type": "array",
                "minItems": len(NARRATIVE_LAYERS),
                "maxItems": len(NARRATIVE_LAYERS),
                "items": _object(
                    {
                        "layer": {"enum": list(NARRATIVE_LAYERS)},
                        "prerequisite": _TEXT,
                        "input_contract": _TEXT,
                        "output_contract": _TEXT,
                        "authority": _TEXT,
                        "quality_gate": _TEXT,
                        "status": _STATUS,
                        "observed_proof_status": _STATUS,
                        "evidence_ids": _TEXTS,
                        "blocked_by": _TEXTS,
                        "revision_semantics": _TEXT,
                    }
                ),
            },
            "evidence_dimensions": _object(
                {
                    name: _object(
                        {
                            "status": _STATUS,
                            "evidence_ids": _TEXTS,
                            "limitations": _TEXTS,
                        }
                    )
                    for name in NARRATIVE_EVIDENCE_DIMENSIONS
                }
            ),
            "sample": _object(
                {
                    "accepted_chapter_numbers": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1},
                    },
                    "sample_size": {"type": "integer", "minimum": 0},
                    "qualification_stage_determined_by_sample_size": {"const": False},
                }
            ),
            "source_receipts": {
                "type": "array",
                "items": _object(
                    {
                        **{
                            key: _TEXT
                            for key in (
                                "receipt_id",
                                "generator",
                                "asset_version_id",
                                "content_hash",
                                "operation_id",
                                "implementation_sha",
                                "generation_sha",
                                "gate_reason",
                            )
                        },
                        "source_table": {
                            "enum": [
                                "authority_narrative_design_qualification",
                                "authority_book_chapter_acceptance",
                            ]
                        },
                        "layer": {"enum": list(NARRATIVE_LAYERS)},
                        "source_class": {
                            "enum": [
                                "REAL_PROVIDER_SEMANTIC",
                                "MODEL_PROVIDER_UNVERIFIED",
                                "SCRIPTED_FIXTURE",
                                "OPERATOR_REVIEW",
                                "ACCEPTED_ACTUAL_CONTRACT",
                            ]
                        },
                        "status": {"enum": ["PASS", "FAIL", "INSUFFICIENT"]},
                        "gate_status": {"enum": ["PASS", "NOT_PROVEN"]},
                        **{
                            key: {"type": "boolean"}
                            for key in (
                                "current",
                                "native_lineage_valid",
                                "profile_current",
                            )
                        },
                        "chapter_number": {"type": "integer", "minimum": 0},
                    }
                ),
            },
            "limitations": _TEXTS,
            "authority_mutation_allowed": {"const": False},
            "evidence_scope": {
                "enum": [
                    "NO_APPROVED_NARRATIVE_INPUT",
                    "FIXTURE_CONTRACT_ONLY",
                    "NATIVE_BOUNDED_EVIDENCE",
                    "HISTORICAL_OR_UNVERIFIED_NATIVE_EVIDENCE",
                ]
            },
            "prose_qualification_allowed": {"type": "boolean"},
        }
    ),
}


def build_narrative_qualification_report(
    *,
    project_id: str,
    book_id: str,
    implementation_sha: str,
    implementation_tree_sha: str,
    receipts: Sequence[NarrativeReceipt],
    engineering_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if (
        not project_id
        or not book_id
        or not re.fullmatch(r"[0-9a-f]{40}", implementation_sha)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", implementation_tree_sha)
    ):
        raise ValueError(
            "Narrative qualification requires exact scope and implementation identity"
        )
    native = sorted(receipts, key=lambda item: item.receipt_id)
    if len({item.receipt_id for item in native}) != len(native):
        raise ValueError("Narrative receipt identities must be unique")
    current = [
        item
        for item in native
        if item.current
        and item.native_lineage_valid
        and item.profile_current
        and item.gate_status == "PASS"
        and item.implementation_sha == implementation_sha
        and item.generation_sha == implementation_sha
    ]
    layer_results = []
    blocked: list[str] = []
    for index, layer in enumerate(NARRATIVE_LAYERS):
        input_contract, output_contract, authority, quality_gate = (
            NARRATIVE_LAYER_CONTRACTS[layer]
        )
        selected = [item for item in current if item.layer == layer]
        source_ids = [item.receipt_id for item in native if item.layer == layer]
        if layer == "TRAJECTORY_PORTFOLIO":
            proof = "DESIGN_REVIEW_REQUIRED"
        elif any(item.status == "FAIL" for item in selected):
            proof = "FAIL"
        elif (
            selected
            and all(
                item.status == "PASS" and item.source_class == "REAL_PROVIDER_SEMANTIC"
                for item in selected
            )
            and {item.generator for item in selected}
            >= _GENERATORS_BY_LAYER.get(layer, {"UNSUPPORTED_NATIVE_GATE"})
        ):
            proof = "PASS"
        elif selected:
            proof = "SUPPORTING_ONLY"
        else:
            proof = "NOT_PROVEN"
        status = (
            "BLOCKED_BY_UPSTREAM"
            if blocked and proof != "DESIGN_REVIEW_REQUIRED"
            else proof
        )
        layer_results.append(
            {
                "layer": layer,
                "prerequisite": NARRATIVE_LAYERS[index - 1] if index else "",
                "input_contract": input_contract,
                "output_contract": output_contract,
                "authority": authority,
                "quality_gate": quality_gate,
                "status": status,
                "observed_proof_status": proof,
                "evidence_ids": source_ids,
                "blocked_by": list(blocked),
                "revision_semantics": "APPEND_REVIEW_EVIDENCE; FUTURE_ONLY_PLAN_CHANGE; ACCEPTED_ACTUAL_IMMUTABLE",
            }
        )
        if proof != "PASS":
            blocked.append(layer)
    engineering = dict(engineering_evidence or {})
    engineering_pass = (
        engineering.get("schema_version")
        == "novel-forge.p0-backend-qualification-report.v2"
        and engineering.get("status") == engineering.get("decision") == "PASS"
        and engineering.get("tested_sha") == implementation_sha
        and engineering.get("implementation_tree_sha") == implementation_tree_sha
        and bool(engineering.get("gates"))
        and all(item.get("status") == "PASS" for item in engineering["gates"])
    )
    dimensions = {
        name: {
            "status": "WAITING_EVIDENCE" if name == "HUMAN_EDITORIAL" else "NOT_PROVEN",
            "evidence_ids": [],
            "limitations": ["INDEPENDENT_NATIVE_EVIDENCE_REQUIRED"],
        }
        for name in NARRATIVE_EVIDENCE_DIMENSIONS
    }
    if engineering_pass:
        dimensions["ENGINEERING"] = {
            "status": "PASS",
            "evidence_ids": [narrative_digest(engineering)],
            "limitations": ["ENGINEERING_ONLY"],
        }
    dimensions["NARRATIVE_CORRECTNESS"] = {
        "status": "FAIL"
        if any(row["observed_proof_status"] == "FAIL" for row in layer_results)
        else "NOT_PROVEN",
        "evidence_ids": [item.receipt_id for item in current],
        "limitations": [
            "TRAJECTORY_PORTFOLIO_OWNER_CONTRACT_DESIGN_REVIEW_REQUIRED",
            "FIXTURE_AND_ACCEPTED_RECEIPT_PROOF_CEILINGS_RETAINED",
        ],
    }
    chapters = sorted(
        {
            item.chapter_number
            for item in native
            if item.layer == "ACCEPTANCE" and item.chapter_number > 0
        }
    )
    inputs = {
        "project_id": project_id,
        "book_id": book_id,
        "receipts": [asdict(item) for item in native],
        "engineering": engineering,
    }
    report = {
        "schema_version": NARRATIVE_REPORT_SCHEMA,
        "project_id": project_id,
        "book_id": book_id,
        "implementation_sha": implementation_sha,
        "implementation_tree_sha": implementation_tree_sha,
        "input_digest": narrative_digest(inputs),
        "status": "FAIL"
        if dimensions["NARRATIVE_CORRECTNESS"]["status"] == "FAIL"
        else "NOT_PROVEN",
        "layers": layer_results,
        "evidence_dimensions": dimensions,
        "sample": {
            "accepted_chapter_numbers": chapters,
            "sample_size": len(chapters),
            "qualification_stage_determined_by_sample_size": False,
        },
        "source_receipts": [asdict(item) for item in native],
        "limitations": [
            "TRAJECTORY_PORTFOLIO_DESIGN_REVIEW_REQUIRED: typed relationship and thematic trajectory lifecycle is not implemented",
            "HUMAN_EDITORIAL_WAITING_EXTERNAL_HUMAN_EVIDENCE",
            "READER_AND_LONGITUDINAL_NATIVE_COMBINED_SCORES_CANNOT_PROVE_INDEPENDENT_DIMENSIONS",
            "ACCEPTED_CHAPTER_RECEIPTS_ALONE_DO_NOT_PROVE_CURRENT_REAL_PROVIDER_OR_PRODUCTION_OPERATION",
        ],
        "authority_mutation_allowed": False,
        "evidence_scope": (
            "NO_APPROVED_NARRATIVE_INPUT"
            if not native
            else "FIXTURE_CONTRACT_ONLY"
            if all(item.source_class == "SCRIPTED_FIXTURE" for item in native)
            else "NATIVE_BOUNDED_EVIDENCE"
            if any(item.source_class == "REAL_PROVIDER_SEMANTIC" for item in current)
            else "HISTORICAL_OR_UNVERIFIED_NATIVE_EVIDENCE"
        ),
        "prose_qualification_allowed": all(
            row["status"] == "PASS" for row in layer_results[:6]
        ),
    }
    report["report_digest"] = narrative_digest(report)
    validate_chapter_provider_output_against_schema(
        "narrative_qualification_report", NARRATIVE_QUALIFICATION_REPORT_SCHEMA, report
    )
    return report
