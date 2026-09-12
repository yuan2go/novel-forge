"""SECURITY: every Content operation uses an explicit frozen-input binder; no generic payload-to-handler escape hatch exists."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from typing import Any, Callable

from novel_forge.modules.authority_handler_runtime import (
    AuthorityHandlerOutput,
    AuthorityHandlerRequest,
    AuthorityInputAsset,
)
from novel_forge.modules.creative.style_projection import compile_foundation_style
from novel_forge.modules.characters.domain import (
    build_character,
    build_relationship_state,
)
from novel_forge.modules.chapter_quality_authority.calibration_v2 import (
    AdjudicatedEvaluation,
    BlindPairPreference,
    CalibrationRun,
    HumanEvaluation,
    JudgeEvaluation,
    QualityProfileVersion,
    ReaderOutcomeEvidence,
    evaluate_quality_calibration_v2,
)
from novel_forge.modules.chapter_quality_authority.domain import QUALITY_DIMENSIONS
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.domain import (
    resolve_book_knowledge_access_policy,
)
from novel_forge.modules.content_intelligence import (
    build_world_consequence_candidate,
    verify_claim,
)
from novel_forge.modules.production_preparation.empty_state import (
    initialize_typed_empty_state,
)
from novel_forge.modules.creative.domain import (
    build_project_proposal,
    cluster_candidates,
    evaluate_candidate,
    validate_creative_brief,
)
from novel_forge.modules.creative.generator_boundary import build_candidate_pool
from novel_forge.modules.ending.domain import (
    build_closure_plan,
    build_payoff_matrix,
    evaluate_ending_quality,
)
from novel_forge.modules.longform_stability.semantic_domain import (
    build_enhanced_recap,
    detect_motivation_drift,
    detect_pattern_repetition,
    detect_power_conflicts,
    detect_world_rule_conflicts,
    evaluate_foreshadow_payoff,
    evaluate_narrative_debt,
    propose_entity_merge,
)
from novel_forge.modules.theme.domain import (
    build_theme_arc,
    evaluate_anti_preaching,
    validate_theme_question,
)
from novel_forge.modules.worldbuilding.domain import (
    build_world_bible,
    validate_world_rules,
)


Binder = Callable[[AuthorityHandlerRequest], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ContentHandlerCodec:
    definition_name: str
    output_asset_type: str
    output_key: str
    bind_and_execute: Binder
    qualification_policy: str = "content-authority-output-v2"

    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        if request.command.get("project_id") != request.project_id:
            raise KernelError(
                "CONTENT_COMMAND_PROJECT_MISMATCH",
                "content command project_id differs from the admitted Operation",
            )
        declared = tuple(request.command.get("input_asset_version_ids") or ())
        frozen = tuple(item.asset_version_id for item in request.inputs)
        if declared != frozen:
            raise KernelError(
                "CONTENT_FROZEN_INPUT_MISMATCH",
                "declared content inputs do not equal the frozen Operation inputs",
            )
        try:
            content = json.loads(
                json.dumps(
                    self.bind_and_execute(request),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        except KernelError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise KernelError(
                "CONTENT_CODEC_INPUT_INVALID",
                f"{self.definition_name} input binding failed: {exc}",
            ) from exc
        return AuthorityHandlerOutput(
            asset_type=self.output_asset_type,
            output_key=self.output_key,
            role="primary",
            content=content,
            qualification_policy=self.qualification_policy,
            reference_asset_version_ids=frozen,
            evidence={
                "codec": self.definition_name,
                "codec_contract_version": "content-codec-v2",
                "input_asset_types": [item.asset_type for item in request.inputs],
            },
        )


def _payload(request: AuthorityHandlerRequest) -> dict[str, Any]:
    value = request.command.get("payload")
    if not isinstance(value, dict):
        raise ValueError("payload must be an object")
    return value


def _one(request: AuthorityHandlerRequest, *types: str) -> AuthorityInputAsset:
    matches = [item for item in request.inputs if item.asset_type in types]
    if len(matches) != 1:
        raise ValueError(f"expected one of {types}, found {len(matches)}")
    return matches[0]


def _many(request: AuthorityHandlerRequest, *types: str) -> list[AuthorityInputAsset]:
    matches = [item for item in request.inputs if item.asset_type in types]
    if not matches:
        raise ValueError(f"expected at least one of {types}")
    return matches


def _creative_brief(request: AuthorityHandlerRequest) -> dict[str, Any]:
    return {
        "project_id": request.project_id,
        **validate_creative_brief(_payload(request)["brief"]),
    }


def _creative_evaluate(request: AuthorityHandlerRequest) -> dict[str, Any]:
    brief = _one(request, "creative_brief")
    candidate = _one(request, "creative_candidate")
    return evaluate_candidate(
        project_id=request.project_id, brief=brief.content, candidate=candidate.content
    )


def _creative_cluster(request: AuthorityHandlerRequest) -> dict[str, Any]:
    evaluations = _many(request, "candidate_evaluation")
    return {
        "project_id": request.project_id,
        "clusters": cluster_candidates(
            [item.content for item in evaluations],
            threshold=float(_payload(request).get("threshold", 0.7)),
        ),
    }


def _creative_approve(request: AuthorityHandlerRequest) -> dict[str, Any]:
    brief = _one(request, "creative_brief")
    evaluations = _many(request, "candidate_evaluation")
    return build_project_proposal(
        project_id=request.project_id,
        brief_version_id=brief.asset_version_id,
        evaluations=[item.content for item in evaluations],
    )


def _world_generate(request: AuthorityHandlerRequest) -> dict[str, Any]:
    brief = _one(request, "creative_brief")
    payload = _payload(request)
    return build_world_bible(
        project_id=request.project_id,
        creative_brief_version_id=brief.asset_version_id,
        rules=list(payload["rules"]),
        entities=dict(payload["entities"]),
    )


def _world_validate(request: AuthorityHandlerRequest) -> dict[str, Any]:
    world = _one(request, "world_bible")
    return validate_world_rules(
        project_id=request.project_id, rules=list(world.content.get("rules", []))
    )


def _world_consequence_analyze(request: AuthorityHandlerRequest) -> dict[str, Any]:
    world = _one(request, "world_bible")
    receipt = _one(request, "world_consequence_provider_receipt")
    consequences = receipt.content.get("consequences")
    if not isinstance(consequences, list):
        raise ValueError("world consequence receipt requires consequences")
    rules = [
        {
            **dict(item),
            "rule_id": str(item.get("rule_id") or item.get("rule_key") or ""),
        }
        for item in world.content.get("rules", [])
        if isinstance(item, dict)
    ]
    return build_world_consequence_candidate(
        project_id=request.project_id,
        world_bible_asset_version_id=world.asset_version_id,
        world_rules=rules,
        provider_consequences=consequences,
        provider_evidence={
            "provider_id": str(receipt.content.get("provider_id") or ""),
            "model_id": str(receipt.content.get("model_id") or ""),
            "prompt_version": str(receipt.content.get("prompt_version") or ""),
            "real_model_call": receipt.content.get("real_model_call") is True,
            "provider_receipt_asset_version_id": receipt.asset_version_id,
            "trace_id": request.trace_id,
            "operation_id": request.operation_id,
        },
    )


def _fact_claim_register(request: AuthorityHandlerRequest) -> dict[str, Any]:
    source = _one(request, "source_document")
    claim = dict(_payload(request).get("claim") or {})
    required = ("claim_id", "statement", "domain", "retrieved_at")
    if any(not str(claim.get(key) or "").strip() for key in required):
        raise ValueError(
            "fact claim identity, statement, domain, and retrieval time are required"
        )
    for key in ("source_quality", "confidence"):
        value = float(claim.get(key, -1))
        if not 0 <= value <= 1:
            raise ValueError(f"{key} must be between zero and one")
    return {
        "type": "Claim",
        "project_id": request.project_id,
        "claim_id": str(claim["claim_id"]),
        "statement": str(claim["statement"]),
        "domain": str(claim["domain"]),
        "source_id": str(claim.get("source_id") or source.asset_version_id),
        "source_asset_version_id": source.asset_version_id,
        "evidence_refs": [],
        "source_published_at": claim.get("source_published_at"),
        "retrieved_at": str(claim["retrieved_at"]),
        "temporal_valid_from": claim.get("temporal_valid_from"),
        "temporal_valid_to": claim.get("temporal_valid_to"),
        "source_quality": float(claim["source_quality"]),
        "confidence": float(claim["confidence"]),
        "status": "PENDING",
        "fictionalization_allowed": bool(claim.get("fictionalization_allowed")),
        "trace_id": request.trace_id,
        "created_by_operation_id": request.operation_id,
        "contract_version": "fact-claim-v1",
    }


def _fact_verify(request: AuthorityHandlerRequest) -> dict[str, Any]:
    claim = _one(request, "fact_claim")
    cards = _many(request, "knowledge_card")
    payload = _payload(request)
    decisions = {
        str(item.get("knowledge_card_asset_version_id") or ""): dict(item)
        for item in payload.get("evidence_decisions", [])
        if isinstance(item, dict)
    }
    evidence: list[dict[str, Any]] = []
    for card in cards:
        decision = decisions.get(card.asset_version_id)
        if decision is None:
            raise ValueError("every frozen KnowledgeCard requires an evidence decision")
        lineage = dict(card.content.get("lineage") or {})
        candidate_version = str(lineage.get("candidate_asset_version_id") or "")
        source_versions = list(lineage.get("source_chunk_asset_version_ids") or [])
        if not candidate_version or not source_versions:
            raise ValueError("KnowledgeCard has no MKAOS source lineage")
        for index, source_version in enumerate(source_versions):
            evidence.append(
                {
                    "project_id": request.project_id,
                    "evidence_span_id": f"{candidate_version}:evidence:{index}",
                    "source_document_id": str(source_version),
                    "knowledge_card_asset_version_id": card.asset_version_id,
                    "stance": str(decision.get("stance") or ""),
                    "qualified": True,
                    "source_quality": float(decision.get("source_quality", 0.0)),
                    "confidence": float(decision.get("confidence", 0.0)),
                    "source_published_at": decision.get("source_published_at"),
                    "retrieved_at": decision.get("retrieved_at"),
                    "temporal_valid_from": decision.get("temporal_valid_from"),
                    "temporal_valid_to": decision.get("temporal_valid_to"),
                }
            )
    as_of_value = str(payload.get("as_of") or "")
    if not as_of_value:
        raise ValueError("fact verification requires an explicit as_of timestamp")
    result = verify_claim(
        claim=claim.content,
        evidence=evidence,
        as_of=datetime.fromisoformat(as_of_value.replace("Z", "+00:00")),
    )
    return {
        **result,
        "statement": str(claim.content["statement"]),
        "domain": str(claim.content["domain"]),
        "fictionalization_allowed": bool(claim.content.get("fictionalization_allowed")),
        "trace_id": request.trace_id,
        "decided_by_operation_id": request.operation_id,
        "claim_asset_version_id": claim.asset_version_id,
        "knowledge_card_asset_version_ids": [card.asset_version_id for card in cards],
    }


def _character_generate(request: AuthorityHandlerRequest) -> dict[str, Any]:
    brief = _one(request, "creative_brief")
    world = _one(request, "world_bible")
    theme = _one(request, "theme_question")
    return build_character(
        project_id=request.project_id,
        creative_brief_version_id=brief.asset_version_id,
        world_bible_version_id=world.asset_version_id,
        theme_question_version_id=theme.asset_version_id,
        profile=dict(_payload(request)["profile"]),
    )


def _relationships_generate(request: AuthorityHandlerRequest) -> dict[str, Any]:
    characters = _many(request, "character_card")
    if len(characters) != 2:
        raise ValueError("relationship generation requires exactly two character cards")
    payload = _payload(request)
    previous = next(
        (item for item in request.inputs if item.asset_type == "relationship_state"),
        None,
    )
    return build_relationship_state(
        project_id=request.project_id,
        left_character_version_id=characters[0].asset_version_id,
        right_character_version_id=characters[1].asset_version_id,
        state=dict(payload["state"]),
        previous_state_version_id=previous.asset_version_id if previous else "",
    )


def _theme_question(request: AuthorityHandlerRequest) -> dict[str, Any]:
    return {
        "project_id": request.project_id,
        **validate_theme_question(str(_payload(request)["question"])),
    }


def _theme_arc(request: AuthorityHandlerRequest) -> dict[str, Any]:
    question = _one(request, "theme_question")
    conflicts = [item.content for item in _many(request, "value_conflict")]
    return build_theme_arc(
        project_id=request.project_id,
        theme_question_version_id=question.asset_version_id,
        conflicts=conflicts,
    )


def _anti_preaching(request: AuthorityHandlerRequest) -> dict[str, Any]:
    target = _one(request, "draft_chapter", "draft_version", "release_package")
    evidence = _one(request, "anti_preaching_evidence")
    return evaluate_anti_preaching(
        project_id=request.project_id,
        target_asset_version_id=target.asset_version_id,
        passages=list(evidence.content.get("passages", [])),
    )


def _closure_plan(request: AuthorityHandlerRequest) -> dict[str, Any]:
    intent = _one(request, "ending_intent")
    return build_closure_plan(
        project_id=request.project_id,
        ending_intent_version_id=intent.asset_version_id,
        plan=dict(_payload(request)["plan"]),
    )


def _payoff_matrix(request: AuthorityHandlerRequest) -> dict[str, Any]:
    items = _many(
        request,
        "promise",
        "foreshadow_state",
        "mystery",
        "relationship_state",
        "character_state",
        "world_rule",
        "reward_ledger",
        "theme_question",
        "antagonist_threat",
    )
    rows = list(_payload(request).get("items", []))
    versions = {item.asset_version_id for item in items}
    if any(str(row.get("asset_version_id")) not in versions for row in rows):
        raise ValueError("payoff item must reference a frozen input version")
    return build_payoff_matrix(project_id=request.project_id, items=rows)


def _ending_quality(request: AuthorityHandlerRequest) -> dict[str, Any]:
    closure = _one(request, "closure_plan")
    matrix = _one(request, "payoff_matrix")
    evidence = _one(request, "ending_evidence")
    return evaluate_ending_quality(
        project_id=request.project_id,
        closure_plan_version_id=closure.asset_version_id,
        payoff_matrix=matrix.content,
        evidence=evidence.content,
    )


def _motivation(request: AuthorityHandlerRequest) -> dict[str, Any]:
    states = _many(request, "character_state")
    behavior = _one(request, "character_behavior")
    return detect_motivation_drift(
        project_id=request.project_id,
        character_state_versions=[
            {"asset_version_id": item.asset_version_id, **item.content}
            for item in states
        ],
        current_behavior={
            "asset_version_id": behavior.asset_version_id,
            **behavior.content,
        },
    )


def _entity_merge(request: AuthorityHandlerRequest) -> dict[str, Any]:
    entities = _many(request, "entity_identity")
    if len(entities) != 2:
        raise ValueError("entity merge requires exactly two identities")
    mentions = [
        item.content for item in request.inputs if item.asset_type == "entity_mention"
    ]
    return propose_entity_merge(
        project_id=request.project_id,
        left=entities[0].content,
        right=entities[1].content,
        mentions=mentions,
    )


def _foreshadow(request: AuthorityHandlerRequest) -> dict[str, Any]:
    thread = _one(request, "foreshadow_state")
    evidence = _one(request, "foreshadow_payoff_evidence")
    return evaluate_foreshadow_payoff(
        project_id=request.project_id,
        thread_version_id=thread.asset_version_id,
        scores=dict(evidence.content["scores"]),
    )


def _world_rule(request: AuthorityHandlerRequest) -> dict[str, Any]:
    rules = _many(request, "world_rule")
    events = [item for item in request.inputs if item.asset_type == "world_event"]
    return detect_world_rule_conflicts(
        project_id=request.project_id,
        rule_versions=[
            {"asset_version_id": item.asset_version_id, **item.content}
            for item in rules
        ],
        events=[
            {"asset_version_id": item.asset_version_id, **item.content}
            for item in events
        ],
    )


def _power(request: AuthorityHandlerRequest) -> dict[str, Any]:
    states = _many(request, "power_state")
    if len(states) != 2:
        raise ValueError("power evaluation requires previous and current states")
    return detect_power_conflicts(
        project_id=request.project_id,
        previous_state={
            "asset_version_id": states[0].asset_version_id,
            **states[0].content,
        },
        current_state={
            "asset_version_id": states[1].asset_version_id,
            **states[1].content,
        },
    )


def _pattern(request: AuthorityHandlerRequest) -> dict[str, Any]:
    rows = _many(request, "narrative_pattern_fingerprint")
    return detect_pattern_repetition(
        project_id=request.project_id,
        fingerprints=[item.content for item in rows],
        threshold=int(_payload(request).get("threshold", 3)),
    )


def _debt(request: AuthorityHandlerRequest) -> dict[str, Any]:
    debts = _many(request, "narrative_debt")
    return evaluate_narrative_debt(
        project_id=request.project_id,
        current_chapter=int(_payload(request)["current_chapter"]),
        debts=[item.content for item in debts],
    )


def _recap(request: AuthorityHandlerRequest) -> dict[str, Any]:
    report_assets = _many(
        request,
        "motivation_drift_report",
        "relationship_report",
        "canon_conflict_report",
        "world_rule_conflict_report",
        "power_conflict_report",
        "foreshadow_payoff_report",
        "narrative_debt_report",
        "reward_cadence_report",
        "antagonist_pressure_report",
        "pattern_repetition_report",
        "theme_movement_report",
        "quality_score_report",
    )
    reports = dict(_payload(request).get("reports", {}))
    for item in report_assets:
        reports.setdefault(item.asset_type, item.content)
    aliases = {
        "motivation": "motivation_drift_report",
        "relationships": "relationship_report",
        "canon": "canon_conflict_report",
        "world_rules": "world_rule_conflict_report",
        "power": "power_conflict_report",
        "foreshadow": "foreshadow_payoff_report",
        "promise_debt": "narrative_debt_report",
        "reward_cadence": "reward_cadence_report",
        "antagonist_pressure": "antagonist_pressure_report",
        "patterns": "pattern_repetition_report",
        "theme": "theme_movement_report",
        "quality": "quality_score_report",
    }
    for key, asset_type in aliases.items():
        if key not in reports and asset_type in reports:
            reports[key] = reports[asset_type]
    return build_enhanced_recap(project_id=request.project_id, reports=reports)


def _creative_candidates_generate(request: AuthorityHandlerRequest) -> dict[str, Any]:
    brief = _one(request, "creative_brief")
    receipt = _one(request, "creative_candidate_generation_receipt")
    return build_candidate_pool(
        project_id=request.project_id,
        creative_brief_asset_version_id=brief.asset_version_id,
        provider_receipt_asset_version_id=receipt.asset_version_id,
        receipt=receipt.content,
    )


def _state_initialize_empty(request: AuthorityHandlerRequest) -> dict[str, Any]:
    evidence = _one(request, "state_absence_evidence")
    payload = _payload(request)
    state_kind = str(payload["state_kind"])
    previous_chapter = int(payload["previous_chapter"])
    return initialize_typed_empty_state(
        project_id=request.project_id,
        operation_id=request.operation_id,
        state_kind=state_kind,
        previous_chapter=previous_chapter,
        reason=str(payload.get("reason") or "explicit authority state initialization"),
        absence_evidence_asset_version_id=evidence.asset_version_id,
        absence_evidence=evidence.content,
    )


def _operator_authored_input(
    request: AuthorityHandlerRequest,
    *,
    asset_type: str,
    required_fields: tuple[str, ...],
) -> dict[str, Any]:
    if request.inputs:
        raise ValueError("operator-authored production inputs cannot inherit assets")
    payload = _payload(request)
    content = payload.get("content")
    if not isinstance(content, dict):
        raise ValueError("operator-authored input content must be an object")
    declared_type = str(content.get("type") or asset_type)
    if declared_type != asset_type:
        raise ValueError(f"operator-authored input must declare type {asset_type}")
    declared_project = str(content.get("project_id") or request.project_id)
    if declared_project != request.project_id:
        raise ValueError("operator-authored input belongs to another project")
    missing = [field for field in required_fields if not content.get(field)]
    if missing:
        raise ValueError(
            "operator-authored input is missing required fields: " + ", ".join(missing)
        )
    if (
        content.get("raw_source") is True
        or content.get("source_expression_included") is True
    ):
        raise ValueError(
            "operator-authored production inputs cannot contain raw source"
        )
    safe_summary = str(content.get("safe_summary") or "").strip()
    structured_facts = content.get("structured_facts")
    if not safe_summary or not isinstance(structured_facts, list):
        raise ValueError(
            "operator-authored input requires safe_summary and structured_facts"
        )
    return {
        **content,
        "type": asset_type,
        "project_id": request.project_id,
        "allowed_use": "generation",
        "raw_source": False,
        "source_expression_included": False,
        "governance_status": "CLEAR",
        "operator_authored": True,
        "evidence_level": "OPERATOR_AUTHORED",
    }


def author_planning_change_request(request: AuthorityHandlerRequest) -> dict[str, Any]:
    content = _operator_authored_input(
        request, asset_type="replan_request",
        required_fields=("book_id", "target_plan_version_id", "directive", "preserved_invariants", "affected_scope"),
    )
    boundary = content.get("accepted_through_chapter")
    if not isinstance(boundary, int) or isinstance(boundary, bool) or boundary < 0:
        raise ValueError("Planning change requires its non-negative accepted boundary")
    if content["affected_scope"] not in {"BOOK", "VOLUME", "ARC", "CHAPTER_GROUP", "CHAPTER"}:
        raise ValueError("Planning change affected scope is unsupported")
    if not isinstance(content["directive"], str) or not content["directive"].strip() or not isinstance(content["preserved_invariants"], list):
        raise ValueError("Planning change requires a directive and preservation list")
    return {**content, "contract_version": "operator-planning-change-request.v1",
            "source_type": "HUMAN_FEEDBACK", "authority_boundary": "FUTURE_PLAN_PROPOSAL_ONLY",
            "direct_plan_mutation_allowed": False, "canon_mutation_allowed": False}


_BOOK_BOOTSTRAP_INPUT_SPECS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "book.production_profile.author": (
        "production_profile",
        ("book_id", "profile_id", "target_chapter_count", "language_contract"),
        "FUTURE_INTENT",
    ),
    "book.previous_volume_outcome.author": (
        "previous_volume_outcome",
        ("book_id", "contract_version", "status"),
        "PRE_CHAPTER_0",
    ),
    "book.previous_chapter_group_outcome.author": (
        "previous_chapter_group_outcome",
        ("book_id", "contract_version", "status"),
        "PRE_CHAPTER_0",
    ),
    "book.previous_chapter_outcome.author": (
        "previous_chapter_outcome",
        ("book_id", "contract_version", "status"),
        "PRE_CHAPTER_0",
    ),
    "book.arc_portfolio.author": (
        "arc_portfolio",
        ("book_id", "portfolio_id", "contract_version"),
        "FUTURE_INTENT",
    ),
    "book.ending_reachability.author": (
        "ending_reachability",
        ("book_id", "contract_version", "status"),
        "ADVISORY",
    ),
    "book.character_arc_portfolio.author": (
        "character_arc_portfolio",
        ("book_id", "portfolio_id", "contract_version"),
        "FUTURE_INTENT",
    ),
    "book.conflict_state.author": (
        "conflict_state",
        ("book_id", "contract_version"),
        "PRE_CHAPTER_0",
    ),
    "book.foreshadowing_ledger.author": (
        "foreshadowing_ledger",
        ("book_id", "contract_version"),
        "PRE_CHAPTER_0",
    ),
    "book.reader_segment.author": (
        "reader_segment_profile",
        ("book_id", "profile_id", "profile_version"),
        "ADVISORY",
    ),
    "book.reader_contract.author": (
        "reader_contract",
        ("book_id", "profile_id", "profile_version"),
        "ADVISORY",
    ),
    "book.reader_state.author": (
        "reader_state",
        ("book_id", "contract_version", "profile_version", "status"),
        "ADVISORY",
    ),
    "book.character_state.author": (
        "character_state_snapshot",
        ("book_id", "contract_version"),
        "PRE_CHAPTER_0",
    ),
    "book.foreshadowing_state.author": (
        "foreshadow_snapshot",
        ("book_id", "contract_version"),
        "PRE_CHAPTER_0",
    ),
    "book.quality_trend.author": (
        "quality_trend",
        ("book_id", "contract_version", "status"),
        "ADVISORY",
    ),
    "book.reward_ledger.author": (
        "reward_ledger_snapshot",
        ("book_id", "contract_version"),
        "PRE_CHAPTER_0",
    ),
    "book.promise_ledger.author": (
        "promise_ledger_snapshot",
        ("book_id", "contract_version"),
        "PRE_CHAPTER_0",
    ),
}

_PRE_CHAPTER_ZERO_ASSET_TYPES = frozenset(
    asset_type
    for asset_type, _required, boundary in _BOOK_BOOTSTRAP_INPUT_SPECS.values()
    if boundary == "PRE_CHAPTER_0"
)


def _author_book_bootstrap_input(
    request: AuthorityHandlerRequest,
    *,
    asset_type: str,
    required_fields: tuple[str, ...],
    authority_boundary: str,
) -> dict[str, Any]:
    content = _operator_authored_input(
        request,
        asset_type=asset_type,
        required_fields=required_fields,
    )
    if str(content.get("book_id") or "").strip() == "":
        raise ValueError("operator-authored Book input requires book_id")
    if content.get("authority_boundary") != authority_boundary:
        raise ValueError(
            f"operator-authored {asset_type} requires {authority_boundary} boundary"
        )
    if _contains_prohibited_bootstrap_claim(content):
        raise ValueError(
            "operator-authored Book input cannot claim human, Provider, or Narrative Truth evidence"
        )
    if asset_type in _PRE_CHAPTER_ZERO_ASSET_TYPES:
        accepted = content.get("accepted_through_chapter", 0)
        if not isinstance(accepted, int) or isinstance(accepted, bool) or accepted != 0:
            raise ValueError(
                f"operator-authored {asset_type} must stay at the pre-Chapter-1 boundary"
            )
        for field in (
            "entries",
            "active_conflicts",
            "current_actual_conflicts",
            "actual_outcomes",
        ):
            if field in content and content[field] != []:
                raise ValueError(
                    f"operator-authored {asset_type} cannot declare accepted {field}"
                )
    if asset_type == "reader_state" and (
        content.get("profile_version") != "reader-outcome-v3"
        or content.get("status") != "NOT_OBSERVED"
        or content.get("accepted_through_chapter") != 0
        or content.get("observations") != []
        or content.get("evidence_class") != "READER_PROXY_ADVISORY"
    ):
        raise ValueError(
            "operator-authored reader_state must be an empty Reader Outcome v3 advisory genesis"
        )
    if asset_type == "production_profile":
        target = content.get("target_chapter_count")
        if not isinstance(target, int) or isinstance(target, bool) or target <= 0:
            raise ValueError("production profile target_chapter_count must be positive")
        if not isinstance(content.get("language_contract"), dict):
            raise ValueError("production profile language_contract must be an object")
        resolve_book_knowledge_access_policy(
            production_profile=content,
            project_id=request.project_id,
            book_id=str(content["book_id"]),
        )
    return {
        **content,
        "provider_generated": False,
        "human_preference_evidence": False,
        "ground_truth_claimed": False,
        "narrative_truth_mutation_allowed": False,
    }


def _book_bootstrap_binder(
    asset_type: str,
    required_fields: tuple[str, ...],
    authority_boundary: str,
) -> Binder:
    def bind(request: AuthorityHandlerRequest) -> dict[str, Any]:
        return _author_book_bootstrap_input(
            request,
            asset_type=asset_type,
            required_fields=required_fields,
            authority_boundary=authority_boundary,
        )

    return bind


def author_initial_story_state(request: AuthorityHandlerRequest) -> dict[str, Any]:
    if request.inputs:
        raise ValueError("initial Story State cannot inherit narrative history")
    payload = _payload(request)
    book_id = str(payload.get("book_id") or "").strip()
    campaign_identity = str(payload.get("campaign_contract_identity") or "")
    if not book_id or not _is_sha256(campaign_identity):
        raise ValueError(
            "initial Story State requires Book scope and SHA-256 campaign identity"
        )
    snapshot: dict[str, Any] = {
        "type": "StoryStateSnapshot",
        "contract_version": "story-state-snapshot-v2",
        "layer": "CURRENT_STATE",
        "project_id": request.project_id,
        "book_id": book_id,
        "scope": {"project_id": request.project_id, "book_id": book_id},
        "accepted_through_chapter": 0,
        "chapter": 0,
        "chapter_number": 0,
        "state_version": 0,
        "current_state": {},
        "reducer_applications": [],
        "accepted_state_only": True,
        "initial_state_boundary": "BOOK_PRODUCTION_INPUT_SNAPSHOT",
        "campaign_contract_identity": campaign_identity,
        "evidence_level": "OPERATOR_AUTHORED_GENESIS",
        "actual_narrative_events": [],
        "future_intent_promoted": False,
        "human_preference_evidence": False,
        "provider_evidence_claimed": False,
    }
    snapshot["state_hash"] = _canonical_sha256(snapshot)
    return snapshot


def author_initial_canon(request: AuthorityHandlerRequest) -> dict[str, Any]:
    story = _one(request, "story_state_snapshot")
    payload = _payload(request)
    book_id = str(payload.get("book_id") or "").strip()
    campaign_identity = str(payload.get("campaign_contract_identity") or "")
    state = dict(story.content)
    state_without_hash = {
        key: value for key, value in state.items() if key != "state_hash"
    }
    if (
        not book_id
        or not _is_sha256(campaign_identity)
        or state.get("contract_version") != "story-state-snapshot-v2"
        or state.get("project_id") != request.project_id
        or state.get("book_id") != book_id
        or state.get("accepted_through_chapter") != 0
        or state.get("current_state") != {}
        or state.get("actual_narrative_events") != []
        or state.get("campaign_contract_identity") != campaign_identity
        or state.get("state_hash") != _canonical_sha256(state_without_hash)
    ):
        raise ValueError("initial Canon requires the exact empty Story State genesis")
    snapshot: dict[str, Any] = {
        "type": "CanonSnapshot",
        "contract_version": "canon-snapshot-v2",
        "layer": "TRUTH",
        "project_id": request.project_id,
        "book_id": book_id,
        "scope": {"project_id": request.project_id, "book_id": book_id},
        "accepted_through_chapter": 0,
        "chapter": 0,
        "chapter_number": 0,
        "current_facts": [],
        "story_state_hash": str(state["state_hash"]),
        "accepted_state_only": True,
        "initial_state_boundary": "BOOK_PRODUCTION_INPUT_SNAPSHOT",
        "campaign_contract_identity": campaign_identity,
        "evidence_level": "OPERATOR_AUTHORED_GENESIS",
        "future_intent_promoted": False,
        "human_preference_evidence": False,
        "provider_evidence_claimed": False,
    }
    snapshot["canon_hash"] = _canonical_sha256(snapshot)
    return snapshot


def _contains_prohibited_bootstrap_claim(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                str(key)
                in {
                    "human_verified",
                    "ground_truth_claimed",
                    "provider_generated",
                    "real_provider_proven",
                    "production_verified",
                    "accepted_actual",
                }
                and item is True
            ):
                return True
            if _contains_prohibited_bootstrap_claim(item):
                return True
    elif isinstance(value, list):
        return any(_contains_prohibited_bootstrap_claim(item) for item in value)
    return False


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _is_sha256(value: str) -> bool:
    digest = value.removeprefix("sha256:")
    return (
        value.startswith("sha256:")
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


def author_chapter_plan(request: AuthorityHandlerRequest) -> dict[str, Any]:
    return _operator_authored_input(
        request,
        asset_type="chapter_plan",
        required_fields=(
            "chapter",
            "title",
            "premise",
            "chapter_objective",
            "scene_sequence",
            "chapter_hook",
        ),
    )


def author_style_policy(request: AuthorityHandlerRequest) -> dict[str, Any]:
    return _operator_authored_input(
        request,
        asset_type="style_policy",
        required_fields=("profile_id", "constraints"),
    )


def author_quality_rubric(request: AuthorityHandlerRequest) -> dict[str, Any]:
    return _operator_authored_input(
        request,
        asset_type="quality_rubric",
        required_fields=("profile_id", "dimensions"),
    )


def author_platform_profile(request: AuthorityHandlerRequest) -> dict[str, Any]:
    return _operator_authored_input(
        request,
        asset_type="platform_profile",
        required_fields=("profile_id", "constraints"),
    )


def author_operator_checklist(request: AuthorityHandlerRequest) -> dict[str, Any]:
    content = _operator_authored_input(
        request,
        asset_type="operator_checklist",
        required_fields=("chapter", "completed", "contract_version"),
    )
    facts = [
        item
        for item in content["structured_facts"]
        if isinstance(item, dict)
        and str(item.get("key") or "") not in {"completed", "contract_version"}
    ]
    return {
        **content,
        "allowed_use": "evidence_only",
        "structured_facts": [
            *facts,
            {"key": "completed", "value": True},
            {"key": "contract_version", "value": content["contract_version"]},
        ],
    }


def author_fixture_waiver_approval(
    request: AuthorityHandlerRequest,
) -> dict[str, Any]:
    content = _operator_authored_input(
        request,
        asset_type="operator_approval",
        required_fields=(
            "book_id",
            "decision",
            "contract_version",
            "waiver_reason",
            "waived_dimensions",
            "scope",
            "expiry",
        ),
    )
    scope = content.get("scope")
    dimensions = content.get("waived_dimensions")
    expiry = str(content.get("expiry") or "")
    try:
        expires_at = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("fixture waiver approval expiry must be ISO-8601") from exc
    if (
        content.get("decision") != "APPROVED"
        or content.get("contract_version") != "fixture-waiver-approval-v1"
        or content.get("fixture_protocol_only") is not True
        or content.get("production_verified") is not False
        or not str(content.get("waiver_reason") or "").strip()
        or not isinstance(dimensions, list)
        or set(str(item) for item in dimensions) != set(QUALITY_DIMENSIONS)
        or not isinstance(scope, dict)
        or scope.get("project_id") != request.project_id
        or scope.get("scope_type") != "PROJECT_FIXTURE"
        or scope.get("release_readiness") != "INTERNAL_REVIEW_RELEASE"
        or expires_at.tzinfo is None
    ):
        raise ValueError(
            "fixture waiver approval must be scoped, expiring, fixture-only, "
            "and cover the canonical Quality dimensions"
        )
    governed_keys = {
        "approved",
        "decision",
        "contract_version",
        "fixture_protocol_only",
        "production_verified",
        "waiver_reason",
        "waived_dimensions",
        "scope",
        "expiry",
        "human_preference_evidence",
    }
    facts = [
        item
        for item in content["structured_facts"]
        if isinstance(item, dict)
        and str(item.get("key") or "") not in governed_keys
    ]
    return {
        **content,
        "allowed_use": "evidence_only",
        "human_preference_evidence": False,
        "structured_facts": [
            *facts,
            {"key": "approved", "value": True},
            {"key": "decision", "value": "APPROVED"},
            {
                "key": "contract_version",
                "value": "fixture-waiver-approval-v1",
            },
            {"key": "fixture_protocol_only", "value": True},
            {"key": "production_verified", "value": False},
            {"key": "waiver_reason", "value": content["waiver_reason"]},
            {"key": "waived_dimensions", "value": list(dimensions)},
            {"key": "scope", "value": dict(scope)},
            {"key": "expiry", "value": expiry},
            {"key": "human_preference_evidence", "value": False},
        ],
    }


def author_story_design_candidate(
    request: AuthorityHandlerRequest,
) -> dict[str, Any]:

    from novel_forge.modules.story_design_authority.validators import (
        validate_story_design_candidate,
    )

    payload = _payload(request)
    content = payload.get("content")
    if not isinstance(content, dict):
        raise ValueError("operator-authored Story Design content must be an object")
    if content.get("operator_authored") is not True:
        raise ValueError("Story Design candidate must declare operator_authored=true")
    if content.get("provider_generated") is not False:
        raise ValueError(
            "operator-authored Story Design cannot claim Provider generation"
        )
    if _contains_forbidden_source_marker(content):
        raise ValueError("operator-authored Story Design cannot contain raw source")
    project_id = str(content.get("project_id") or "")
    generator = str(content.get("generator_operation_name") or "")
    planning_scope = str(content.get("planning_scope") or "")
    logical_key = str(content.get("logical_key") or "")
    if project_id != request.project_id:
        raise ValueError("operator-authored Story Design belongs to another Project")
    candidate_payload = content.get("candidate_payload")
    if not isinstance(candidate_payload, dict):
        raise ValueError("operator-authored Story Design requires candidate_payload")
    if "narrative_intent_source" in candidate_payload:
        if generator != "creative.candidates.generate" or "narrative_intent" in candidate_payload:
            raise ValueError("Intent source compilation belongs to Creative Foundation and cannot create a second interpretation")
        from dataclasses import asdict
        from novel_forge.modules.story_design_authority.intent import compile_narrative_intent
        candidate_payload = dict(candidate_payload)
        source = candidate_payload.pop("narrative_intent_source")
        candidate_payload["narrative_intent"] = asdict(compile_narrative_intent(source))
        candidate_payload["narrative_intent"]["must_have"] = list(candidate_payload["narrative_intent"]["must_have"])
        candidate_payload["narrative_intent"]["must_not"] = list(candidate_payload["narrative_intent"]["must_not"])
        candidate_payload["intent_compiler_version"] = "labeled-narrative-intent.v1"
        content = {**content, "candidate_payload": candidate_payload}
    bindings = candidate_payload.get("foundation_parent_bindings") or {}
    if not isinstance(bindings, dict):
        raise ValueError("Foundation parent bindings must be an object")
    declared_parents = {
        (
            str(item.get("asset_version_id") or ""),
            str(item.get("content_hash") or ""),
        )
        for item in bindings.values()
        if isinstance(item, dict)
    }
    frozen_parents = {
        (item.asset_version_id, item.content_hash) for item in request.inputs
    }
    if declared_parents != frozen_parents or any(
        not all(item) for item in declared_parents
    ):
        raise ValueError(
            "Foundation parent bindings must equal the exact frozen input AssetVersions"
        )
    validate_story_design_candidate(
        content=content,
        project_id=request.project_id,
        generator_operation_name=generator,
        planning_scope=planning_scope,
        logical_key=logical_key,
    )
    return dict(content)


_STORY_DESIGN_AUTHOR_SPECS = {
    "story_design.creative_foundation.author": (
        "creative_foundation",
        "creative.candidates.generate",
    ),
    "story_design.theme_contract.author": (
        "theme_contract",
        "theme.candidates.generate",
    ),
    "story_design.ending_intent.author": (
        "ending_intent",
        "ending.intent.generate",
    ),
    "story_design.reader_promise.author": (
        "reader_promise",
        "reader.promise.generate",
    ),
    "story_design.world_bible.author": (
        "world_bible",
        "world.design.generate",
    ),
    "story_design.character_cast.author": (
        "character_cast",
        "character.cast.generate",
    ),
}


def _story_design_author_binder(generator_operation_name: str) -> Binder:
    def bind(request: AuthorityHandlerRequest) -> dict[str, Any]:
        content = author_story_design_candidate(request)
        if content.get("generator_operation_name") != generator_operation_name:
            raise ValueError(
                "operator-authored Story Design operation and generator differ"
            )
        return content

    return bind


def author_story_design_review(request: AuthorityHandlerRequest) -> dict[str, Any]:
    candidate = _one(
        request,
        "creative_foundation",
        "theme_contract",
        "ending_intent",
        "reader_promise",
        "world_bible",
        "character_cast",
        "book_design",
        "planning_generation_candidate",
    )
    payload = _payload(request)
    evaluation = payload.get("evaluation")
    if not isinstance(evaluation, dict) or not evaluation:
        raise ValueError("operator Story Design review requires an evaluation")
    if (
        str(payload.get("candidate_asset_version_id") or "")
        != candidate.asset_version_id
    ):
        raise ValueError("operator Story Design review targets another candidate")
    if str(payload.get("candidate_content_hash") or "") != candidate.content_hash:
        raise ValueError("operator Story Design review candidate hash drifted")
    rationale = str(payload.get("review_rationale") or "").strip()
    if not rationale:
        raise ValueError("operator Story Design review requires a rationale")
    return {
        "type": "NarrativeDesignOperatorReviewEvidence",
        "contract_version": "narrative-design-operator-review.v1",
        "project_id": request.project_id,
        "candidate_asset_version_id": candidate.asset_version_id,
        "candidate_content_hash": candidate.content_hash,
        "evaluation": dict(evaluation),
        "review_rationale": rationale,
        "evaluator_execution_class": "OPERATOR_REVIEW",
        "human_preference_evidence": False,
        "ground_truth_claimed": False,
        "provider_evidence_claimed": False,
    }


def _contains_forbidden_source_marker(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                str(key) in {"raw_source", "source_expression_included"}
                and item is True
            ):
                return True
            if _contains_forbidden_source_marker(item):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_source_marker(item) for item in value)
    return False


def _quality_profile_v2_create(request: AuthorityHandlerRequest) -> dict[str, Any]:
    payload = dict(_payload(request)["profile"])
    profile = QualityProfileVersion(
        profile_version_id=str(payload["profile_version_id"]),
        profile_id=str(payload["profile_id"]),
        version=int(payload["version"]),
        dimension=str(payload["dimension"]),
        threshold_policy_version_id=str(payload["threshold_policy_version_id"]),
        thresholds=dict(payload["thresholds"]),
        judge_profile_ref=str(payload["judge_profile_ref"]),
        judge_profile_hash=str(payload["judge_profile_hash"]),
        judge_provider_id=str(payload["judge_provider_id"]),
        judge_model_id=str(payload["judge_model_id"]),
        previous_profile_version_id=str(
            payload.get("previous_profile_version_id") or ""
        ),
        status=str(payload.get("status") or "CANDIDATE"),
    )
    return {
        "type": "QualityProfileVersion",
        "contract_version": "quality-profile-version-v2",
        "project_id": request.project_id,
        **asdict(profile),
        "thresholds": dict(profile.thresholds),
        "production_verified": False,
    }


def _judge_evaluation_v2_record(request: AuthorityHandlerRequest) -> dict[str, Any]:
    payload = dict(_payload(request)["evaluation"])
    subject_id = str(payload["subject_asset_version_id"])
    provider_result_id = str(payload["provider_result_asset_version_id"])
    _require_frozen_version(request, subject_id)
    _require_frozen_version(request, provider_result_id)
    evaluation = JudgeEvaluation(
        evaluation_id=str(payload["evaluation_id"]),
        subject_asset_version_id=subject_id,
        dimension=str(payload["dimension"]),
        status=str(payload["status"]),
        score=payload.get("score"),
        confidence=float(payload["confidence"]),
        evaluator_id=str(payload["evaluator_id"]),
        provider_id=str(payload["provider_id"]),
        model_id=str(payload["model_id"]),
        generator_provider_id=str(payload["generator_provider_id"]),
        generator_model_id=str(payload["generator_model_id"]),
        reviewer_provider_id=str(payload["reviewer_provider_id"]),
        reviewer_model_id=str(payload["reviewer_model_id"]),
        prompt_version=str(payload["prompt_version"]),
        prompt_hash=str(payload["prompt_hash"]),
        result_asset_version_id=provider_result_id,
    )
    return {
        "type": "JudgeEvaluation",
        "contract_version": "judge-evaluation-v2",
        "project_id": request.project_id,
        **asdict(evaluation),
        "calibrated": False,
        "self_qualification_allowed": False,
    }


def _human_evaluation_v2_record(request: AuthorityHandlerRequest) -> dict[str, Any]:
    payload = dict(_payload(request)["evaluation"])
    subject_id = str(payload["subject_asset_version_id"])
    _require_frozen_version(request, subject_id)
    evaluation = HumanEvaluation(
        evaluation_id=str(payload["evaluation_id"]),
        subject_asset_version_id=subject_id,
        dimension=str(payload["dimension"]),
        status=str(payload["status"]),
        score=payload.get("score"),
        evaluator_id=str(payload["evaluator_id"]),
        evaluator_group=str(payload["evaluator_group"]),
        evaluator_identity_class=str(payload["evaluator_identity_class"]),
        protocol_version=str(payload["protocol_version"]),
        evaluation_version=str(payload["evaluation_version"]),
        scope_type=str(payload["scope_type"]),
        chapter_start=int(payload["chapter_start"]),
        chapter_end=int(payload["chapter_end"]),
        confidence=float(payload["confidence"]),
        evidence=tuple(payload.get("evidence") or ()),
        blind=bool(payload.get("blind", False)),
        evaluation_asset_version_id=str(payload["evaluation_id"]),
    )
    return {
        "type": "HumanEvaluation",
        "contract_version": "human-evaluation-v2",
        "project_id": request.project_id,
        **{
            key: value
            for key, value in asdict(evaluation).items()
            if key != "evaluation_asset_version_id"
        },
        "ground_truth": False,
        "subjective_evaluation_requires_adjudication": True,
    }


def _adjudication_v2_record(request: AuthorityHandlerRequest) -> dict[str, Any]:
    payload = dict(_payload(request)["adjudication"])
    humans = _many(request, "human_evaluation")
    subject_id = str(payload["subject_asset_version_id"])
    _require_frozen_version(request, subject_id)
    human_ids = tuple(item.asset_version_id for item in humans)
    declared = tuple(payload["source_human_evaluation_asset_version_ids"])
    if human_ids != declared:
        raise ValueError("adjudication inputs differ from frozen HumanEvaluations")
    adjudication = AdjudicatedEvaluation(
        adjudication_id=str(payload["adjudication_id"]),
        subject_asset_version_id=subject_id,
        dimension=str(payload["dimension"]),
        status=str(payload["status"]),
        score_range=tuple(payload["score_range"]),
        source_human_evaluation_asset_version_ids=human_ids,
        adjudicator_id=str(payload["adjudicator_id"]),
        adjudicator_identity_class=str(payload["adjudicator_identity_class"]),
        protocol_version=str(payload["protocol_version"]),
        evaluation_version=str(payload["evaluation_version"]),
        scope_type=str(payload["scope_type"]),
        chapter_start=int(payload["chapter_start"]),
        chapter_end=int(payload["chapter_end"]),
        rationale=str(payload["rationale"]),
        adjudication_asset_version_id=str(payload["adjudication_id"]),
    )
    return {
        "type": "AdjudicatedEvaluation",
        "contract_version": "adjudicated-evaluation-v2",
        "project_id": request.project_id,
        **{
            key: value
            for key, value in asdict(adjudication).items()
            if key != "adjudication_asset_version_id"
        },
        "single_human_evaluation_is_ground_truth": False,
    }


def _blind_pair_preference_v2_record(
    request: AuthorityHandlerRequest,
) -> dict[str, Any]:
    payload = dict(_payload(request)["preference"])
    candidate_a_id = str(payload["candidate_a_asset_version_id"])
    candidate_b_id = str(payload["candidate_b_asset_version_id"])
    _require_frozen_version(request, candidate_a_id)
    _require_frozen_version(request, candidate_b_id)
    preference = BlindPairPreference(
        preference_id=str(payload["preference_id"]),
        pair_id=str(payload["pair_id"]),
        subject_id=str(payload["subject_id"]),
        candidate_a_asset_version_id=candidate_a_id,
        candidate_b_asset_version_id=candidate_b_id,
        choice=str(payload["choice"]),
        evaluator_id=str(payload["evaluator_id"]),
        evaluator_role=str(payload["evaluator_role"]),
        evaluator_identity_class=str(payload["evaluator_identity_class"]),
        protocol_version=str(payload["protocol_version"]),
        evaluation_version=str(payload["evaluation_version"]),
        scope_type=str(payload["scope_type"]),
        chapter_start=int(payload["chapter_start"]),
        chapter_end=int(payload["chapter_end"]),
        presentation_order=str(payload["presentation_order"]),
        dimension_scores=dict(payload["dimension_scores"]),
        confidence=float(payload["confidence"]),
        rationale=str(payload["rationale"]),
        preference_asset_version_id=str(payload["preference_id"]),
    )
    return {
        "type": "BlindPairPreference",
        "contract_version": "blind-pair-preference-v2",
        "project_id": request.project_id,
        **{
            key: value
            for key, value in asdict(preference).items()
            if key != "preference_asset_version_id"
        },
        "blind_comparison": True,
        "narrative_truth_mutation_allowed": False,
    }


def _reader_outcome_evidence_v2_record(
    request: AuthorityHandlerRequest,
) -> dict[str, Any]:
    payload = dict(_payload(request)["evidence"])
    subject_id = str(payload["subject_asset_version_id"])
    _require_frozen_version(request, subject_id)
    evidence = ReaderOutcomeEvidence(
        evidence_id=str(payload["evidence_id"]),
        subject_asset_version_id=subject_id,
        metric_type=str(payload["metric_type"]),
        exposure_count=int(payload["exposure_count"]),
        outcome_count=int(payload["outcome_count"]),
        reader_segment=str(payload["reader_segment"]),
        platform=str(payload["platform"]),
        evidence_asset_version_id=str(payload["evidence_id"]),
    )
    return {
        "type": "ReaderOutcomeEvidence",
        "contract_version": "reader-outcome-evidence-v2",
        "project_id": request.project_id,
        **{
            key: value
            for key, value in asdict(evidence).items()
            if key != "evidence_asset_version_id"
        },
        "narrative_truth_mutation_allowed": False,
    }


def _calibration_v2_run(request: AuthorityHandlerRequest) -> dict[str, Any]:
    profile_asset = _one(request, "quality_profile_version")
    judge_assets = _many(request, "judge_evaluation")
    human_assets = _many(request, "human_evaluation")
    adjudication_assets = _many(request, "adjudicated_evaluation")
    blind_assets = _many(request, "blind_pair_preference")
    reader_assets = _many(request, "reader_outcome_evidence")
    profile_content = dict(profile_asset.content)
    profile = QualityProfileVersion(
        **{
            key: profile_content[key]
            for key in QualityProfileVersion.__dataclass_fields__
            if key in profile_content
        }
    )
    payload = _payload(request)
    run = CalibrationRun(
        run_id=str(payload["run_id"]),
        profile_version_id=profile_asset.asset_version_id,
        dimension=profile.dimension,
        protocol_version=str(payload["protocol_version"]),
        evaluation_version=str(payload["evaluation_version"]),
        evidence_scope=str(payload.get("evidence_scope") or "BOUNDED_EVIDENCE"),
        judge_evaluation_asset_version_ids=tuple(
            item.asset_version_id for item in judge_assets
        ),
        adjudicated_evaluation_asset_version_ids=tuple(
            item.asset_version_id for item in adjudication_assets
        ),
        human_evaluation_asset_version_ids=tuple(
            item.asset_version_id for item in human_assets
        ),
        blind_pair_preference_asset_version_ids=tuple(
            item.asset_version_id for item in blind_assets
        ),
        reader_outcome_evidence_asset_version_ids=tuple(
            item.asset_version_id for item in reader_assets
        ),
        fixture_protocol_only=bool(payload.get("fixture_protocol_only", False)),
    )
    profile = QualityProfileVersion(
        **{
            **asdict(profile),
            "profile_version_id": profile_asset.asset_version_id,
        }
    )
    result = evaluate_quality_calibration_v2(
        run=run,
        profile=profile,
        judge_evaluations=tuple(
            _judge_evaluation_from_asset(item) for item in judge_assets
        ),
        human_evaluations=tuple(
            _human_evaluation_from_asset(item) for item in human_assets
        ),
        adjudicated_evaluations=tuple(
            _adjudication_from_asset(item) for item in adjudication_assets
        ),
        blind_preferences=tuple(
            BlindPairPreference(
                **{
                    **{
                        key: item.content[key]
                        for key in BlindPairPreference.__dataclass_fields__
                        if key in item.content
                    },
                    "preference_asset_version_id": item.asset_version_id,
                }
            )
            for item in blind_assets
        ),
        reader_outcomes=tuple(
            ReaderOutcomeEvidence(
                **{
                    **{
                        key: item.content[key]
                        for key in ReaderOutcomeEvidence.__dataclass_fields__
                        if key in item.content
                    },
                    "evidence_asset_version_id": item.asset_version_id,
                }
            )
            for item in reader_assets
        ),
    )
    return {
        "type": "CalibrationResult",
        "project_id": request.project_id,
        **asdict(result),
        "diagnostics": dict(result.diagnostics),
    }


def _require_frozen_version(
    request: AuthorityHandlerRequest, asset_version_id: str
) -> AuthorityInputAsset:
    matches = [
        item for item in request.inputs if item.asset_version_id == asset_version_id
    ]
    if len(matches) != 1:
        raise ValueError("evaluation references an asset outside frozen inputs")
    return matches[0]


def _judge_evaluation_from_asset(item: AuthorityInputAsset) -> JudgeEvaluation:
    content = dict(item.content)
    return JudgeEvaluation(
        **{
            **{
                key: content[key]
                for key in JudgeEvaluation.__dataclass_fields__
                if key in content
            },
            "result_asset_version_id": item.asset_version_id,
        }
    )


def _human_evaluation_from_asset(item: AuthorityInputAsset) -> HumanEvaluation:
    content = dict(item.content)
    return HumanEvaluation(
        **{
            **{
                key: content[key]
                for key in HumanEvaluation.__dataclass_fields__
                if key in content
            },
            "evidence": tuple(content.get("evidence") or ()),
            "evaluation_asset_version_id": item.asset_version_id,
        }
    )


def _adjudication_from_asset(item: AuthorityInputAsset) -> AdjudicatedEvaluation:
    content = dict(item.content)
    return AdjudicatedEvaluation(
        **{
            **{
                key: content[key]
                for key in AdjudicatedEvaluation.__dataclass_fields__
                if key in content
            },
            "score_range": tuple(content["score_range"]),
            "source_human_evaluation_asset_version_ids": tuple(
                content["source_human_evaluation_asset_version_ids"]
            ),
            "adjudication_asset_version_id": item.asset_version_id,
        }
    )


CONTENT_CODECS: dict[str, ContentHandlerCodec] = {
    name: ContentHandlerCodec(name, asset_type, output_key, binder)
    for name, asset_type, output_key, binder in (
        ("creative.brief.create", "creative_brief", "creative.brief", _creative_brief),
        ("planning.change_request.author", "replan_request", "planning.change_request", author_planning_change_request),
        (
            "creative.candidates.evaluate",
            "candidate_evaluation",
            "creative.candidate_evaluation",
            _creative_evaluate,
        ),
        (
            "creative.candidates.cluster",
            "candidate_cluster",
            "creative.candidate_cluster",
            _creative_cluster,
        ),
        (
            "creative.project.approve",
            "project_proposal",
            "creative.project_proposal",
            _creative_approve,
        ),
        ("production.world.generate", "world_bible", "world.bible", _world_generate),
        (
            "world.validate",
            "world_rule_conflict_report",
            "world.validation",
            _world_validate,
        ),
        (
            "world.consequence.materialize_candidate",
            "world_consequence_graph",
            "world.consequence",
            _world_consequence_analyze,
        ),
        (
            "production.character.generate",
            "character_card",
            "character.card",
            _character_generate,
        ),
        (
            "character.relationships.generate",
            "relationship_state",
            "character.relationship",
            _relationships_generate,
        ),
        ("theme.question.create", "theme_question", "theme.question", _theme_question),
        ("theme.arc.build", "theme_arc", "theme.arc", _theme_arc),
        (
            "theme.anti_preaching.evaluate",
            "anti_preaching_report",
            "theme.anti_preaching",
            _anti_preaching,
        ),
        ("ending.closure.plan", "closure_plan", "ending.closure", _closure_plan),
        (
            "ending.payoff_matrix.build",
            "payoff_matrix",
            "ending.payoff_matrix",
            _payoff_matrix,
        ),
        (
            "ending.quality.evaluate",
            "ending_quality_report",
            "ending.quality",
            _ending_quality,
        ),
        (
            "longform.motivation.evaluate",
            "motivation_drift_report",
            "longform.motivation",
            _motivation,
        ),
        (
            "longform.entity_merge.propose",
            "entity_merge_proposal",
            "longform.entity_merge",
            _entity_merge,
        ),
        (
            "longform.foreshadow_payoff.evaluate",
            "foreshadow_payoff_report",
            "longform.foreshadow_payoff",
            _foreshadow,
        ),
        (
            "longform.world_rule.evaluate",
            "world_rule_conflict_report",
            "longform.world_rule",
            _world_rule,
        ),
        ("longform.power.evaluate", "power_conflict_report", "longform.power", _power),
        (
            "longform.pattern.evaluate",
            "pattern_repetition_report",
            "longform.pattern",
            _pattern,
        ),
        (
            "longform.narrative_debt.evaluate",
            "narrative_debt_report",
            "longform.narrative_debt",
            _debt,
        ),
        ("longform.recap.enhance", "longform_recap_report", "longform.recap", _recap),
        ("fact.claim.register", "fact_claim", "fact.claim", _fact_claim_register),
        ("fact.verify", "fact_verification_report", "fact.verification", _fact_verify),
        (
            "quality.profile.v2.create",
            "quality_profile_version",
            "quality.profile.v2",
            _quality_profile_v2_create,
        ),
        (
            "quality.judge_evaluation.record",
            "judge_evaluation",
            "quality.judge_evaluation",
            _judge_evaluation_v2_record,
        ),
        (
            "quality.human_evaluation.record",
            "human_evaluation",
            "quality.human_evaluation",
            _human_evaluation_v2_record,
        ),
        (
            "quality.adjudication.record",
            "adjudicated_evaluation",
            "quality.adjudication",
            _adjudication_v2_record,
        ),
        (
            "quality.blind_pair_preference.record",
            "blind_pair_preference",
            "quality.blind_pair_preference",
            _blind_pair_preference_v2_record,
        ),
        (
            "quality.reader_outcome_evidence.record",
            "reader_outcome_evidence",
            "quality.reader_outcome_evidence",
            _reader_outcome_evidence_v2_record,
        ),
        (
            "quality.calibration.v2.run",
            "calibration_result",
            "quality.calibration.v2.result",
            _calibration_v2_run,
        ),
        (
            "chapter.state.initialize_empty",
            "typed_empty_state_snapshot",
            "chapter.state.empty_snapshot",
            _state_initialize_empty,
        ),
        ("chapter.plan.author", "chapter_plan", "chapter.plan", author_chapter_plan),
        ("chapter.style_policy.compile", "style_policy", "chapter.style_policy", compile_foundation_style),
        (
            "chapter.style_policy.author",
            "style_policy",
            "chapter.style_policy",
            author_style_policy,
        ),
        (
            "chapter.quality_rubric.author",
            "quality_rubric",
            "chapter.quality_rubric",
            author_quality_rubric,
        ),
        (
            "chapter.platform_profile.author",
            "platform_profile",
            "chapter.platform_profile",
            author_platform_profile,
        ),
        (
            "chapter.operator_checklist.author",
            "operator_checklist",
            "chapter.operator_checklist",
            author_operator_checklist,
        ),
        (
            "chapter.fixture_waiver_approval.author",
            "operator_approval",
            "chapter.fixture_waiver_approval",
            author_fixture_waiver_approval,
        ),
        *(
            (
                name,
                asset_type,
                f"story_design.{asset_type}",
                _story_design_author_binder(generator),
            )
            for name, (asset_type, generator) in _STORY_DESIGN_AUTHOR_SPECS.items()
        ),
        (
            "story_design.review.author",
            "narrative_design_operator_review",
            "story_design.operator_review",
            author_story_design_review,
        ),
        *(
            (
                name,
                asset_type,
                f"book.bootstrap.{asset_type}",
                _book_bootstrap_binder(asset_type, required_fields, boundary),
            )
            for name, (
                asset_type,
                required_fields,
                boundary,
            ) in _BOOK_BOOTSTRAP_INPUT_SPECS.items()
        ),
        (
            "book.initial_story_state.author",
            "story_state_snapshot",
            "book.bootstrap.initial_story_state",
            author_initial_story_state,
        ),
        (
            "book.initial_canon.author",
            "canon_snapshot",
            "book.bootstrap.initial_canon",
            author_initial_canon,
        ),
        (
            "creative.candidates.generate",
            "creative_candidate_pool",
            "creative.candidates.pool",
            _creative_candidates_generate,
        ),
    )
}

__all__ = [
    "CONTENT_CODECS",
    "ContentHandlerCodec",
    "author_initial_canon",
    "author_initial_story_state",
    "author_chapter_plan",
    "author_platform_profile",
    "author_operator_checklist",
    "author_fixture_waiver_approval",
    "author_quality_rubric",
    "author_story_design_candidate",
    "author_story_design_review",
    "author_style_policy",
]
