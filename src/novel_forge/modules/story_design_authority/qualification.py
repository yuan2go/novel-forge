"""CONSTRAINT: a layer-specific evaluation contract cannot act as a universal narrative judge."""

from __future__ import annotations
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping
from novel_forge.modules.command_kernel.errors import KernelError
from .domain import GENERATOR_CATALOG

NARRATIVE_QUALIFICATION_SCHEMA_VERSION = "progressive-narrative-qualification.v1"
PROVIDER_JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


class NarrativeDesignLayer(StrEnum):
    STORY_INTENT = "STORY_INTENT"
    STORY_FOUNDATION = "STORY_FOUNDATION"
    BOOK_ARCHITECTURE = "BOOK_ARCHITECTURE"
    VOLUME_ARCHITECTURE = "VOLUME_ARCHITECTURE"
    NARRATIVE_ARC_GRAPH = "NARRATIVE_ARC_GRAPH"
    CHARACTER_DEVELOPMENT = "CHARACTER_DEVELOPMENT"
    DISCLOSURE_OBLIGATION = "DISCLOSURE_OBLIGATION"
    NARRATIVE_SCHEDULING = "NARRATIVE_SCHEDULING"
    NARRATIVE_REALIZATION_PROOF = "NARRATIVE_REALIZATION_PROOF"
    CHAPTER_EXECUTION_PLAN = "CHAPTER_EXECUTION_PLAN"
    CHAPTER_MISSION = "CHAPTER_MISSION"
    SCENE_ARCHITECTURE = "SCENE_ARCHITECTURE"


@dataclass(frozen=True, slots=True)
class NarrativeQualificationProfile:
    layer: NarrativeDesignLayer
    profile_id: str
    profile_version: str
    capability_id: str
    skill_ref: str
    criteria: tuple[str, ...]

    @property
    def profile_hash(self) -> str:
        return _canonical_hash(
            {
                **asdict(self),
                **(
                    {"criterion_semantics": self.criterion_semantics}
                    if self.profile_version == "3.0.0"
                    else {}
                ),
            }
        )

    @property
    def criterion_semantics(self) -> dict[str, str]:
        if self.profile_version != "3.0.0":
            return {}
        return {
            criterion: _WORK_METHOD_SEMANTICS.get(
                criterion, _WORK_APPLICABILITY_SEMANTICS
            )
            for criterion in self.criteria
        }


@dataclass(frozen=True, slots=True)
class NarrativeQualificationReceipt:
    layer: NarrativeDesignLayer
    status: str
    profile_id: str
    profile_version: str
    profile_hash: str
    capability_id: str
    skill_ref: str
    criterion_count: int
    evaluation_hash: str
    evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class NarrativeQualificationResult:
    status: str
    schema_version: str
    qualification_hash: str
    receipts: tuple[NarrativeQualificationReceipt, ...]

    def to_evidence(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "schema_version": self.schema_version,
            "qualification_hash": self.qualification_hash,
            "receipts": [
                {**asdict(receipt), "layer": receipt.layer.value}
                for receipt in self.receipts
            ],
        }


@dataclass(frozen=True, slots=True)
class NarrativeEvaluationLineage:
    generation_operation_id: str
    evaluation_operation_id: str
    evaluation_attempt_id: str
    evaluation_asset_version_id: str
    candidate_asset_version_id: str
    candidate_content_hash: str
    evaluator_execution_class: str
    evaluation_evidence_hash: str
    provider_model_call_asset_version_id: str = ""
    provider_model_call_content_hash: str = ""
    provider_evidence_hash: str = ""
    provider_result_hash: str = ""
    provider_route_snapshot_id: str = ""

    def __post_init__(self) -> None:
        required = (
            self.generation_operation_id,
            self.evaluation_operation_id,
            self.evaluation_attempt_id,
            self.evaluation_asset_version_id,
            self.candidate_asset_version_id,
        )
        if any(not item.strip() for item in required):
            raise KernelError(
                "NARRATIVE_EVALUATION_LINEAGE_INCOMPLETE",
                "Narrative evaluation requires immutable Operation, Attempt, AssetVersion, and candidate lineage",
            )
        if self.generation_operation_id == self.evaluation_operation_id:
            raise KernelError(
                "NARRATIVE_EVALUATION_NOT_INDEPENDENT",
                "candidate generation cannot mint its own Narrative Qualification",
            )
        if self.evaluator_execution_class not in {
            "MODEL_PROVIDER",
            "SCRIPTED_FIXTURE",
            "OPERATOR_REVIEW",
        }:
            raise KernelError(
                "NARRATIVE_EVALUATOR_EXECUTION_CLASS_INVALID",
                "Narrative evaluation execution class is unsupported",
            )
        for label, value in (
            ("candidate content", self.candidate_content_hash),
            ("evaluation evidence", self.evaluation_evidence_hash),
        ):
            if not value.startswith("sha256:"):
                raise KernelError(
                    "NARRATIVE_EVALUATION_LINEAGE_INVALID",
                    f"{label} must be SHA-256 bound",
                )
        provider_values = (
            self.provider_model_call_asset_version_id,
            self.provider_model_call_content_hash,
            self.provider_evidence_hash,
            self.provider_result_hash,
            self.provider_route_snapshot_id,
        )
        if self.evaluator_execution_class == "MODEL_PROVIDER":
            if any(not value for value in provider_values):
                raise KernelError(
                    "NARRATIVE_EVALUATION_PROVIDER_LINEAGE_INCOMPLETE",
                    "model-provider evaluation requires exact ModelCallLog, result, route, and evidence lineage",
                )
            for label, value in (
                ("ModelCallLog content", self.provider_model_call_content_hash),
                ("Provider evidence", self.provider_evidence_hash),
                ("Provider result", self.provider_result_hash),
            ):
                if not value.startswith("sha256:"):
                    raise KernelError(
                        "NARRATIVE_EVALUATION_PROVIDER_LINEAGE_INVALID",
                        f"{label} must be SHA-256 bound",
                    )
        elif any(provider_values):
            raise KernelError(
                "NARRATIVE_EVALUATION_PROVIDER_LINEAGE_INVALID",
                "non-provider evaluation cannot claim Provider lineage",
            )

    def to_evidence(self) -> dict[str, str]:
        return asdict(self)


def _profile(
    layer: NarrativeDesignLayer,
    profile_id: str,
    capability_id: str,
    skill_ref: str,
    *criteria: str,
) -> NarrativeQualificationProfile:
    return NarrativeQualificationProfile(
        layer=layer,
        profile_id=profile_id,
        profile_version="1.0.0",
        capability_id=capability_id,
        skill_ref=skill_ref,
        criteria=tuple(criteria),
    )


_BOOK_DESIGN_PROFILES = (
    _profile(
        NarrativeDesignLayer.STORY_INTENT,
        "story-intent-semantic-v1",
        "creative.proposal.generate",
        "topic-development",
        "PREMISE_COHERENCE",
        "THEME_CONFLICT_ALIGNMENT",
        "GENRE_READER_PROMISE_ALIGNMENT",
        "ENDING_INTENT_REACHABILITY",
        "CORE_CONFLICT_CLARITY",
    ),
    _profile(
        NarrativeDesignLayer.STORY_FOUNDATION,
        "story-foundation-semantic-v1",
        "world.design.generate",
        "worldbuilding",
        "WORLD_RULE_COHERENCE",
        "CHARACTER_CONFLICT_FIT",
        "OPPOSITION_CAPACITY",
        "NARRATIVE_DNA_DISTINCTNESS",
        "LONGFORM_FOUNDATION_CAPACITY",
    ),
)


_FOUNDATION_QUALIFICATION_PROFILES = {
    "creative.candidates.generate": (
        _profile(
            NarrativeDesignLayer.STORY_INTENT,
            "creative-foundation-semantic-v1",
            GENERATOR_CATALOG["creative.candidates.generate"].capability,
            "topic-development",
            "CORE_CONFLICT_CLARITY",
            "READER_FIT",
            "DIFFERENTIATION",
            "SERIALIZATION_CAPACITY",
            "EMOTIONAL_CONTRACT",
        ),
    ),
    "theme.candidates.generate": (
        _profile(
            NarrativeDesignLayer.STORY_INTENT,
            "theme-contract-semantic-v1",
            GENERATOR_CATALOG["theme.candidates.generate"].capability,
            "narrative-beat-design",
            "THEMATIC_QUESTION_CLARITY",
            "CONFLICT_PRESSURE",
            "CHARACTER_CHOICE_RELEVANCE",
            "ENDING_ALIGNMENT",
            "ANTI_PREACHING_CAPACITY",
        ),
    ),
    "ending.intent.generate": (
        _profile(
            NarrativeDesignLayer.STORY_INTENT,
            "ending-intent-semantic-v1",
            GENERATOR_CATALOG["ending.intent.generate"].capability,
            "long-outline",
            "ENDING_DIRECTION_CLARITY",
            "PROTAGONIST_COST",
            "TRANSFORMATION_REACHABILITY",
            "THEME_CLOSURE_ALIGNMENT",
            "LONGFORM_REACHABILITY",
        ),
    ),
    "reader.promise.generate": (
        _profile(
            NarrativeDesignLayer.STORY_INTENT,
            "reader-promise-semantic-v1",
            GENERATOR_CATALOG["reader.promise.generate"].capability,
            "hot-novel-business-deconstruction",
            "PROMISE_SPECIFICITY",
            "GENRE_ALIGNMENT",
            "REWARD_REACHABILITY",
            "PAYOFF_EXPECTATION_CLARITY",
            "SUSTAINABLE_CADENCE",
        ),
    ),
    "world.design.generate": (
        _profile(
            NarrativeDesignLayer.STORY_FOUNDATION,
            "world-foundation-semantic-v1",
            GENERATOR_CATALOG["world.design.generate"].capability,
            "worldbuilding",
            "WORLD_RULE_COHERENCE",
            "RULE_COST_AND_LIMIT",
            "CONFLICT_GENERATION_CAPACITY",
            "CHARACTER_AGENCY_SUPPORT",
            "LONGFORM_EVOLUTION_CAPACITY",
        ),
    ),
    "character.cast.generate": (
        _profile(
            NarrativeDesignLayer.CHARACTER_DEVELOPMENT,
            "character-cast-semantic-v1",
            GENERATOR_CATALOG["character.cast.generate"].capability,
            "character-design",
            "CHARACTER_AGENCY",
            "DESIRE_NEED_CONFLICT",
            "VOICE_DIFFERENTIATION",
            "RELATIONSHIP_FUNCTION",
            "ARC_REACHABILITY",
        ),
    ),
}


GENERATOR_QUALIFICATION_PROFILES: Mapping[
    str, tuple[NarrativeQualificationProfile, ...]
] = MappingProxyType(
    {
        **_FOUNDATION_QUALIFICATION_PROFILES,
        "book_design.propose": _BOOK_DESIGN_PROFILES,
        "book_plan.generate": (
            _profile(
                NarrativeDesignLayer.BOOK_ARCHITECTURE,
                "book-architecture-semantic-v1",
                GENERATOR_CATALOG["book_plan.generate"].capability,
                "long-outline",
                "NARRATIVE_CAPACITY",
                "CONFLICT_SUSTAINABILITY",
                "ENDING_REACHABILITY",
                "TRANSFORMATION_REACHABILITY",
                "THEME_REACHABILITY",
            ),
            _profile(
                NarrativeDesignLayer.CHARACTER_DEVELOPMENT,
                "character-development-semantic-v1",
                GENERATOR_CATALOG["book_plan.generate"].capability,
                "character-design",
                "CAUSAL_TRAJECTORY",
                "BELIEF_CHANGE_CAUSALITY",
                "RELATIONSHIP_PROGRESSION",
                "POWER_RESOURCE_CONSEQUENCE",
                "ENDING_TRANSFORMATION_ALIGNMENT",
            ),
            _profile(
                NarrativeDesignLayer.DISCLOSURE_OBLIGATION,
                "disclosure-obligation-semantic-v1",
                GENERATOR_CATALOG["book_plan.generate"].capability,
                "canon-continuity-graph",
                "TRUTH_KNOWLEDGE_SEPARATION",
                "DISCLOSURE_COHERENCE",
                "SETUP_PAYOFF_REACHABILITY",
                "MYSTERY_SUSTAINABILITY",
                "OBLIGATION_LOAD",
            ),
        ),
        "volume_plan.generate": (
            _profile(
                NarrativeDesignLayer.VOLUME_ARCHITECTURE,
                "volume-architecture-semantic-v1",
                GENERATOR_CATALOG["volume_plan.generate"].capability,
                "long-outline",
                "DISTINCT_VOLUME_FUNCTION",
                "PRESSURE_ESCALATION",
                "IRREVERSIBLE_CHANGE",
                "CLIMAX_PAYOFF_COST",
                "NEXT_VOLUME_BRIDGE",
            ),
        ),
        "arc_plan.generate": (
            _profile(
                NarrativeDesignLayer.NARRATIVE_ARC_GRAPH,
                "narrative-arc-graph-semantic-v1",
                GENERATOR_CATALOG["arc_plan.generate"].capability,
                "canon-continuity-graph",
                "ARC_DEVELOPMENT_CAUSALITY",
                "DEPENDENCY_RELATION_VALIDITY",
                "CROSS_VOLUME_CADENCE",
                "CONVERGENCE",
                "CLOSURE_REACHABILITY",
            ),
        ),
        "chapter_group_plan.generate": (
            _profile(
                NarrativeDesignLayer.NARRATIVE_SCHEDULING,
                "narrative-scheduling-semantic-v1",
                GENERATOR_CATALOG["chapter_group_plan.generate"].capability,
                "narrative-beat-design",
                "CHAPTER_FUNCTION_DIVERSITY",
                "ARC_CADENCE",
                "PAYOFF_DISTRIBUTION",
                "READER_EXPERIENCE_RHYTHM",
                "NARRATIVE_DENSITY_BALANCE",
                "DORMANCY_REACTIVATION",
                "OBLIGATION_CONGESTION",
            ),
            _profile(
                NarrativeDesignLayer.NARRATIVE_REALIZATION_PROOF,
                "narrative-realization-proof-semantic-v1",
                GENERATOR_CATALOG["chapter_group_plan.generate"].capability,
                "narrative-beat-design",
                "CANON_STATE_LEGAL",
                "CHARACTER_MOTIVATION_LEGAL",
                "WORLD_RULES_LEGAL",
                "KNOWLEDGE_BOUNDARIES_LEGAL",
                "CAUSAL_ESCALATION",
                "STATE_TRANSITION_COVERAGE",
                "OBLIGATION_LIFECYCLE",
                "ARC_CONTRIBUTION_COVERAGE",
                "NARRATIVE_LOAD_LEGAL",
                "CHAPTER_DECOMPOSITION_LEGAL",
            ),
        ),
        "chapter_plan.generate": (
            _profile(
                NarrativeDesignLayer.CHAPTER_MISSION,
                "chapter-mission-semantic-v2",
                GENERATOR_CATALOG["chapter_plan.generate"].capability,
                "chapter-outline",
                "UPSTREAM_ALIGNMENT",
                "ARC_MOVEMENT",
                "CHARACTER_CAUSALITY",
                "KNOWLEDGE_BOUNDARY_COHERENCE",
                "EXIT_STATE_REACHABILITY",
                "OBLIGATION_COMMITMENT_COVERAGE",
            ),
            _profile(
                NarrativeDesignLayer.SCENE_ARCHITECTURE,
                "scene-architecture-semantic-v2",
                GENERATOR_CATALOG["chapter_plan.generate"].capability,
                "narrative-beat-design",
                "SCENE_PURPOSE",
                "CONFLICT_ESCALATION",
                "INFORMATION_PROGRESSION",
                "STATE_TRANSITION_COVERAGE",
                "READER_EFFECT",
                "CHAPTER_EXIT_REACHABILITY",
                "MISSION_REALIZATION_COVERAGE",
            ),
        ),
    }
)


def uses_work_requirements(content: Mapping[str, Any]) -> bool:
    if content.get("schema_version") in {"book-design.v6", "book-design.v7"}:
        return True
    payload = content.get("candidate_payload", content)
    if not isinstance(payload, Mapping):
        return False
    envelope = payload.get("constraint_envelope")
    return isinstance(envelope, Mapping) and (
        envelope.get("contract_version")
        in {"foundation-generation.v2", "foundation-generation.v3"}
        or envelope.get("creative_requirements_contract")
        in {"work-requirements.v1", "work-requirements.v2"}
    )


_WORK_APPLICABILITY_SEMANTICS = (
    "Evaluate this criterion against frozen author requirements and this work's valid commitments. "
    "A method that is absent, explicitly inapplicable or prohibited is not required: validate the "
    "chosen alternative and record PASS with its input/candidate evidence if coherent, with no "
    "repair_directive. This is a pass of alignment, not a claim that the omitted method occurred. "
    "Explicitly selected or adopted commitments remain mandatory; missing/contradictory execution "
    "is FAIL, genuinely missing evidence is INSUFFICIENT. Neither verdict may invent an unselected "
    "method as a repair. Unknown applicability does not prove absence or authorize invention."
)
_WORK_METHOD_SEMANTICS = {
    "THEME_METHOD_WORK_ALIGNMENT": _WORK_APPLICABILITY_SEMANTICS
    + " Theme exploration may use observation, ambiguity, reflection, exposition or choices. "
    "Check every selected choice test and its consequences when present; empty choice_tests "
    "can be valid for an observational theme. Characters need not enact competing choices.",
    "ENDING_THEME_WORK_ALIGNMENT": _WORK_APPLICABILITY_SEMANTICS
    + " Check intended thematic relation and every selected closure condition. An open or "
    "unresolved ending with stable characters can align with the theme; closure, transformation "
    "and protagonist cost are not prerequisites. Do not fill an empty closure_conditions array.",
}


def qualification_profile_options(content: Mapping[str, Any]) -> dict[str, Any]:
    payload = content.get("candidate_payload", content)
    envelope = (
        payload.get("constraint_envelope") if isinstance(payload, Mapping) else None
    )
    aligned = content.get("schema_version") == "book-design.v7" or (
        isinstance(envelope, Mapping)
        and (
            envelope.get("contract_version") == "foundation-generation.v3"
            or envelope.get("creative_requirements_contract") == "work-requirements.v2"
        )
    )
    return {
        "work_requirements": uses_work_requirements(content),
        "profile_version": "3.0.0" if aligned else "2.0.0",
    }


_WORK_CRITERIA = {
    "SUSTAINABLE_CADENCE": "SELECTED_PROMISE_CADENCE_ALIGNMENT",
    "CONFLICT_GENERATION_CAPACITY": "WORLD_NARRATIVE_PURPOSE_SUPPORT",
    "CHAPTER_FUNCTION_DIVERSITY": "CHAPTER_FUNCTION_WORK_ALIGNMENT",
    "READER_EXPERIENCE_RHYTHM": "SELECTED_READER_EXPERIENCE_RHYTHM",
    "NARRATIVE_DENSITY_BALANCE": "SELECTED_NARRATIVE_DENSITY_ALIGNMENT",
    "POWER_RESOURCE_CONSEQUENCE": "APPLICABLE_POWER_RESOURCE_CONSEQUENCE",
    "VOICE_DIFFERENTIATION": "SELECTED_VOICE_ALIGNMENT",
    "ARC_REACHABILITY": "SELECTED_CHARACTER_ARC_REACHABILITY",
    "RELATIONSHIP_PROGRESSION": "RELATIONSHIP_CONTINUITY_OR_CHANGE",
    "CROSS_VOLUME_CADENCE": "SELECTED_CROSS_VOLUME_CADENCE",
    "CONVERGENCE": "SELECTED_ARC_RELATION_ALIGNMENT",
    "CORE_CONFLICT_CLARITY": "NARRATIVE_PURPOSE_CLARITY",
    "CONFLICT_PRESSURE": "THEMATIC_EXPRESSION_SUPPORT",
    "ANTI_PREACHING_CAPACITY": "THEME_PRESENTATION_ALIGNMENT",
    "PROTAGONIST_COST": "SELECTED_ENDING_REQUIREMENTS_ALIGNMENT",
    "SERIALIZATION_CAPACITY": "WORK_LENGTH_CAPACITY",
    "RULE_COST_AND_LIMIT": "RULE_APPLICABILITY_AND_LIMITS",
    "DESIRE_NEED_CONFLICT": "CHARACTER_DESIGN_ALIGNMENT",
    "OPPOSITION_CAPACITY": "STORY_PRESSURE_OR_OBSERVATION_FIT",
    "TRANSFORMATION_REACHABILITY": "CHARACTER_CONTINUITY_OR_CHANGE",
    "REWARD_REACHABILITY": "SELECTED_EXPERIENCE_REACHABILITY",
    "PAYOFF_EXPECTATION_CLARITY": "SELECTED_PROMISE_ALIGNMENT",
    "PRESSURE_ESCALATION": "VOLUME_PURPOSE_ALIGNMENT",
    "IRREVERSIBLE_CHANGE": "SELECTED_VOLUME_OUTCOME_ALIGNMENT",
    "CLIMAX_PAYOFF_COST": "SELECTED_VOLUME_COMMITMENT_COVERAGE",
    "NEXT_VOLUME_BRIDGE": "ENDING_OR_CONTINUATION_ALIGNMENT",
    "BELIEF_CHANGE_CAUSALITY": "BELIEF_CONTINUITY_OR_CHANGE_COHERENCE",
    "ENDING_TRANSFORMATION_ALIGNMENT": "CHARACTER_ENDING_ALIGNMENT",
    "CAUSAL_ESCALATION": "CAUSAL_ALIGNMENT",
    "ARC_MOVEMENT": "APPLICABLE_ARC_COMMITMENT_COVERAGE",
    "CONFLICT_ESCALATION": "SCENE_INTENT_ALIGNMENT",
    "INFORMATION_PROGRESSION": "APPLICABLE_INFORMATION_COVERAGE",
    "STATE_TRANSITION_COVERAGE": "APPLICABLE_STATE_TRANSITION_COVERAGE",
    "PAYOFF_DISTRIBUTION": "SELECTED_PAYOFF_DISTRIBUTION",
    "DORMANCY_REACTIVATION": "SELECTED_ARC_CADENCE_ALIGNMENT",
    "CONFLICT_SUSTAINABILITY": "NARRATIVE_PURPOSE_SUSTAINABILITY",
    "CHARACTER_CONFLICT_FIT": "CHARACTER_WORK_FIT",
    "LONGFORM_FOUNDATION_CAPACITY": "WORK_FOUNDATION_CAPACITY",
    "THEME_CONFLICT_ALIGNMENT": "THEME_NARRATIVE_ALIGNMENT",
    "MYSTERY_SUSTAINABILITY": "SELECTED_MYSTERY_ALIGNMENT",
}


def qualification_profiles_for_asset(
    cursor: Any, *, project_id: str, asset_version_id: str, generator: str
) -> tuple[NarrativeQualificationProfile, ...]:
    cursor.execute(
        """SELECT v.content FROM authority_asset_version v
        JOIN authority_asset a ON a.asset_id=v.asset_id
        WHERE a.project_id=%s AND v.asset_version_id=%s""",
        [project_id, asset_version_id],
    )
    row = cursor.fetchone()
    if row is None or not isinstance(row[0], Mapping):
        raise KernelError(
            "NARRATIVE_QUALIFICATION_TARGET_REQUIRED",
            "Profile selection requires the exact immutable candidate within this project",
        )
    return required_qualification_profiles(
        generator, **qualification_profile_options(row[0])
    )


def required_qualification_profiles(
    generator_operation_name: str,
    *,
    work_requirements: bool = False,
    profile_version: str = "2.0.0",
) -> tuple[NarrativeQualificationProfile, ...]:
    if profile_version not in {"2.0.0", "3.0.0"}:
        raise KernelError(
            "NARRATIVE_QUALIFICATION_PROFILE_UNSUPPORTED",
            "Unknown frozen work profile version",
        )
    try:
        profiles = GENERATOR_QUALIFICATION_PROFILES[generator_operation_name]
        return (
            tuple(
                replace(
                    profile,
                    profile_id=profile.profile_id
                    + ("-work-v3" if profile_version == "3.0.0" else "-work-v2"),
                    profile_version=profile_version,
                    criteria=tuple(
                        (
                            {
                                "CHARACTER_CHOICE_RELEVANCE": "THEME_METHOD_WORK_ALIGNMENT",
                                "THEME_CLOSURE_ALIGNMENT": "ENDING_THEME_WORK_ALIGNMENT",
                            }.get(criterion, _WORK_CRITERIA.get(criterion, criterion))
                            if profile_version == "3.0.0"
                            else _WORK_CRITERIA.get(criterion, criterion)
                        )
                        for criterion in profile.criteria
                    ),
                )
                for profile in profiles
            )
            if work_requirements
            else profiles
        )
    except KeyError as exc:
        raise KernelError(
            "NARRATIVE_QUALIFICATION_PROFILE_NOT_FOUND",
            "no Narrative Qualification profile is registered for the design stage",
        ) from exc


def validate_narrative_qualification(
    *,
    generator_operation_name: str,
    value: Any,
    require_pass: bool = True,
    work_requirements: bool = False,
    profile_version: str = "2.0.0",
) -> NarrativeQualificationResult:
    profiles = required_qualification_profiles(
        generator_operation_name,
        work_requirements=work_requirements,
        profile_version=profile_version,
    )
    if not isinstance(value, Mapping) or (
        value.get("schema_version") != NARRATIVE_QUALIFICATION_SCHEMA_VERSION
    ):
        raise KernelError(
            "NARRATIVE_SEMANTIC_EVALUATION_REQUIRED",
            "candidate requires a versioned Narrative Semantic Evaluation",
        )
    evaluations = value.get("evaluations")
    if not isinstance(evaluations, list):
        raise KernelError(
            "NARRATIVE_SEMANTIC_EVALUATION_INVALID",
            "Narrative Semantic Evaluation entries must be an array",
        )
    by_layer: dict[NarrativeDesignLayer, Mapping[str, Any]] = {}
    for item in evaluations:
        if not isinstance(item, Mapping):
            raise KernelError(
                "NARRATIVE_SEMANTIC_EVALUATION_INVALID",
                "Narrative Semantic Evaluation entries must be objects",
            )
        try:
            layer = NarrativeDesignLayer(str(item.get("layer") or ""))
        except ValueError as exc:
            raise KernelError(
                "NARRATIVE_SEMANTIC_EVALUATION_INVALID",
                "Narrative Semantic Evaluation uses an unknown design layer",
            ) from exc
        if layer in by_layer:
            raise KernelError(
                "NARRATIVE_SEMANTIC_EVALUATION_INVALID",
                "Narrative Semantic Evaluation repeats one design layer",
            )
        by_layer[layer] = item
    expected_layers = {profile.layer for profile in profiles}
    if set(by_layer) != expected_layers:
        raise KernelError(
            "NARRATIVE_SEMANTIC_EVALUATION_INVALID",
            "Narrative Semantic Evaluation layers differ from the stage profile",
        )

    receipts: list[NarrativeQualificationReceipt] = []
    failures: list[str] = []
    for profile in profiles:
        evaluation = by_layer[profile.layer]
        profile_verdicts: list[str] = []
        identity = (
            str(evaluation.get("profile_id") or ""),
            str(evaluation.get("profile_version") or ""),
            str(evaluation.get("profile_hash") or ""),
            str(evaluation.get("capability_id") or ""),
            str(evaluation.get("skill_ref") or ""),
        )
        expected_identity = (
            profile.profile_id,
            profile.profile_version,
            profile.profile_hash,
            profile.capability_id,
            profile.skill_ref,
        )
        if identity != expected_identity:
            raise KernelError(
                "NARRATIVE_SEMANTIC_PROFILE_DRIFT",
                f"{profile.layer.value} evaluation differs from its frozen profile",
            )
        criteria = evaluation.get("criteria")
        if not isinstance(criteria, list):
            raise KernelError(
                "NARRATIVE_SEMANTIC_EVALUATION_INVALID",
                f"{profile.layer.value} evaluation criteria must be an array",
            )
        by_criterion: dict[str, Mapping[str, Any]] = {}
        for criterion in criteria:
            if not isinstance(criterion, Mapping):
                raise KernelError(
                    "NARRATIVE_SEMANTIC_EVALUATION_INVALID",
                    "Narrative criterion must be an object",
                )
            criterion_id = str(criterion.get("criterion") or "")
            if not criterion_id or criterion_id in by_criterion:
                raise KernelError(
                    "NARRATIVE_SEMANTIC_EVALUATION_INVALID",
                    "Narrative criteria require unique identities",
                )
            by_criterion[criterion_id] = criterion
        if set(by_criterion) != set(profile.criteria):
            raise KernelError(
                "NARRATIVE_SEMANTIC_EVALUATION_INVALID",
                f"{profile.layer.value} evaluation criteria differ from the profile",
            )
        for criterion_id in profile.criteria:
            criterion = by_criterion[criterion_id]
            verdict = str(criterion.get("verdict") or "")
            rationale = str(criterion.get("rationale") or "").strip()
            evidence_refs = criterion.get("evidence_refs")
            repair = str(criterion.get("repair_directive") or "").strip()
            if (
                verdict not in {"PASS", "FAIL", "INSUFFICIENT"}
                or not rationale
                or not isinstance(evidence_refs, list)
                or not evidence_refs
                or any(not str(ref).strip() for ref in evidence_refs)
                or (verdict != "PASS" and not repair)
                or (verdict == "PASS" and repair)
            ):
                raise KernelError(
                    "NARRATIVE_SEMANTIC_EVALUATION_INVALID",
                    f"{profile.layer.value}/{criterion_id} verdict evidence is invalid",
                )
            if verdict != "PASS":
                failures.append(f"{profile.layer.value}:{criterion_id}:{verdict}")
            profile_verdicts.append(verdict)
        evaluation_dict = dict(evaluation)
        profile_status = (
            "FAIL"
            if "FAIL" in profile_verdicts
            else "INSUFFICIENT"
            if "INSUFFICIENT" in profile_verdicts
            else "PASS"
        )
        receipts.append(
            NarrativeQualificationReceipt(
                layer=profile.layer,
                status=profile_status,
                profile_id=profile.profile_id,
                profile_version=profile.profile_version,
                profile_hash=profile.profile_hash,
                capability_id=profile.capability_id,
                skill_ref=profile.skill_ref,
                criterion_count=len(profile.criteria),
                evaluation_hash=_canonical_hash(evaluation_dict),
                evidence=evaluation_dict,
            )
        )
    if failures and require_pass:
        raise KernelError(
            "NARRATIVE_SEMANTIC_QUALIFICATION_FAILED",
            ", ".join(failures),
        )
    status = (
        "FAIL"
        if any(receipt.status == "FAIL" for receipt in receipts)
        else "INSUFFICIENT"
        if any(receipt.status == "INSUFFICIENT" for receipt in receipts)
        else "PASS"
    )
    evidence = {
        "schema_version": NARRATIVE_QUALIFICATION_SCHEMA_VERSION,
        "generator_operation_name": generator_operation_name,
        "status": status,
        "receipts": [
            {
                "layer": receipt.layer.value,
                "status": receipt.status,
                "profile_hash": receipt.profile_hash,
                "evaluation_hash": receipt.evaluation_hash,
            }
            for receipt in receipts
        ],
    }
    return NarrativeQualificationResult(
        status=status,
        schema_version=NARRATIVE_QUALIFICATION_SCHEMA_VERSION,
        qualification_hash=_canonical_hash(evidence),
        receipts=tuple(receipts),
    )


def scripted_qualification(
    generator_operation_name: str,
    *,
    work_requirements: bool = False,
    profile_version: str = "2.0.0",
) -> dict[str, Any]:

    return {
        "schema_version": NARRATIVE_QUALIFICATION_SCHEMA_VERSION,
        "evaluations": [
            {
                "layer": profile.layer.value,
                "profile_id": profile.profile_id,
                "profile_version": profile.profile_version,
                "profile_hash": profile.profile_hash,
                "capability_id": profile.capability_id,
                "skill_ref": profile.skill_ref,
                "criteria": [
                    {
                        "criterion": criterion,
                        "verdict": "PASS",
                        "rationale": (
                            f"Scripted fixture satisfies {criterion} for contract testing."
                        ),
                        "evidence_refs": [f"fixture:{profile.layer.value}:{criterion}"],
                        "repair_directive": "",
                    }
                    for criterion in profile.criteria
                ],
            }
            for profile in required_qualification_profiles(
                generator_operation_name,
                work_requirements=work_requirements,
                profile_version=profile_version,
            )
        ],
    }


def qualification_provider_schema(
    generator_operation_name: str,
    *,
    work_requirements: bool = False,
    profile_version: str = "2.0.0",
) -> dict[str, Any]:
    profiles = required_qualification_profiles(
        generator_operation_name,
        work_requirements=work_requirements,
        profile_version=profile_version,
    )
    string = {"type": "string", "minLength": 1}
    criterion = _strict_object(
        {
            "criterion": string,
            "verdict": {
                "type": "string",
                "enum": ["PASS", "FAIL", "INSUFFICIENT"],
            },
            "rationale": string,
            "evidence_refs": {
                "type": "array",
                "minItems": 1,
                "items": string,
            },
            "repair_directive": {"type": "string"},
        }
    )
    evaluation = _strict_object(
        {
            "layer": {
                "type": "string",
                "enum": [profile.layer.value for profile in profiles],
            },
            "profile_id": {
                "type": "string",
                "enum": [profile.profile_id for profile in profiles],
            },
            "profile_version": {
                "type": "string",
                "const": profile_version if work_requirements else "1.0.0",
            },
            "profile_hash": {
                "type": "string",
                "enum": [profile.profile_hash for profile in profiles],
            },
            "capability_id": {
                "type": "string",
                "enum": [profile.capability_id for profile in profiles],
            },
            "skill_ref": {
                "type": "string",
                "enum": [profile.skill_ref for profile in profiles],
            },
            "criteria": {
                "type": "array",
                "minItems": min(len(profile.criteria) for profile in profiles),
                "maxItems": max(len(profile.criteria) for profile in profiles),
                "items": criterion,
            },
        }
    )
    return {
        "$schema": PROVIDER_JSON_SCHEMA_DIALECT,
        **_strict_object(
            {
                "schema_version": {
                    "type": "string",
                    "const": NARRATIVE_QUALIFICATION_SCHEMA_VERSION,
                },
                "evaluations": {
                    "type": "array",
                    "minItems": len(profiles),
                    "maxItems": len(profiles),
                    "items": evaluation,
                },
            }
        ),
    }


def _strict_object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _canonical_hash(value: Any) -> str:
    import hashlib
    import json

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "GENERATOR_QUALIFICATION_PROFILES",
    "NARRATIVE_QUALIFICATION_SCHEMA_VERSION",
    "NarrativeDesignLayer",
    "NarrativeEvaluationLineage",
    "NarrativeQualificationProfile",
    "NarrativeQualificationReceipt",
    "NarrativeQualificationResult",
    "qualification_provider_schema",
    "required_qualification_profiles",
    "scripted_qualification",
    "validate_narrative_qualification",
]
