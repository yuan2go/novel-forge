"""Explicit frozen-input codecs for Content Authority operations.

Each binder names and validates its inputs.  There is deliberately no generic
``handler(**payload)`` escape hatch.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Callable

from novel_forge.modules.authority_handler_runtime import (
    AuthorityHandlerOutput,
    AuthorityHandlerRequest,
    AuthorityInputAsset,
)
from novel_forge.modules.characters.domain import build_character, build_relationship_state
from novel_forge.modules.chapter_quality_authority.calibration import (
    QualityCalibrationPolicy,
    QualityCalibrationProfile,
    QualityCalibrationRun,
    QualityCalibrationStatus,
    QualityGoldenSample,
    QualityHumanDecision,
    QualityProviderDecision,
    evaluate_calibration_run,
    promote_calibration_profile,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.creative.domain import (
    build_project_proposal,
    cluster_candidates,
    evaluate_candidate,
    validate_creative_brief,
)
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
from novel_forge.modules.worldbuilding.domain import build_world_bible, validate_world_rules


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
    return {"project_id": request.project_id, **validate_creative_brief(_payload(request)["brief"])}


def _creative_evaluate(request: AuthorityHandlerRequest) -> dict[str, Any]:
    brief = _one(request, "creative_brief")
    candidate = _one(request, "creative_candidate")
    return evaluate_candidate(project_id=request.project_id, brief=brief.content, candidate=candidate.content)


def _creative_cluster(request: AuthorityHandlerRequest) -> dict[str, Any]:
    evaluations = _many(request, "candidate_evaluation")
    return {"project_id": request.project_id, "clusters": cluster_candidates([item.content for item in evaluations], threshold=float(_payload(request).get("threshold", .7)))}


def _creative_approve(request: AuthorityHandlerRequest) -> dict[str, Any]:
    brief = _one(request, "creative_brief")
    evaluations = _many(request, "candidate_evaluation")
    return build_project_proposal(project_id=request.project_id, brief_version_id=brief.asset_version_id, evaluations=[item.content for item in evaluations])


def _world_generate(request: AuthorityHandlerRequest) -> dict[str, Any]:
    brief = _one(request, "creative_brief")
    payload = _payload(request)
    return build_world_bible(project_id=request.project_id, creative_brief_version_id=brief.asset_version_id, rules=list(payload["rules"]), entities=dict(payload["entities"]))


def _world_validate(request: AuthorityHandlerRequest) -> dict[str, Any]:
    world = _one(request, "world_bible")
    return validate_world_rules(project_id=request.project_id, rules=list(world.content.get("rules", [])))


def _character_generate(request: AuthorityHandlerRequest) -> dict[str, Any]:
    brief = _one(request, "creative_brief")
    world = _one(request, "world_bible")
    theme = _one(request, "theme_question")
    return build_character(project_id=request.project_id, creative_brief_version_id=brief.asset_version_id, world_bible_version_id=world.asset_version_id, theme_question_version_id=theme.asset_version_id, profile=dict(_payload(request)["profile"]))


def _relationships_generate(request: AuthorityHandlerRequest) -> dict[str, Any]:
    characters = _many(request, "character_card")
    if len(characters) != 2:
        raise ValueError("relationship generation requires exactly two character cards")
    payload = _payload(request)
    previous = next((item for item in request.inputs if item.asset_type == "relationship_state"), None)
    return build_relationship_state(project_id=request.project_id, left_character_version_id=characters[0].asset_version_id, right_character_version_id=characters[1].asset_version_id, state=dict(payload["state"]), previous_state_version_id=previous.asset_version_id if previous else "")


def _theme_question(request: AuthorityHandlerRequest) -> dict[str, Any]:
    return {"project_id": request.project_id, **validate_theme_question(str(_payload(request)["question"]))}


def _theme_arc(request: AuthorityHandlerRequest) -> dict[str, Any]:
    question = _one(request, "theme_question")
    conflicts = [item.content for item in _many(request, "value_conflict")]
    return build_theme_arc(project_id=request.project_id, theme_question_version_id=question.asset_version_id, conflicts=conflicts)


def _anti_preaching(request: AuthorityHandlerRequest) -> dict[str, Any]:
    target = _one(request, "draft_chapter", "draft_version", "release_package")
    evidence = _one(request, "anti_preaching_evidence")
    return evaluate_anti_preaching(project_id=request.project_id, target_asset_version_id=target.asset_version_id, passages=list(evidence.content.get("passages", [])))


def _closure_plan(request: AuthorityHandlerRequest) -> dict[str, Any]:
    intent = _one(request, "ending_intent")
    return build_closure_plan(project_id=request.project_id, ending_intent_version_id=intent.asset_version_id, plan=dict(_payload(request)["plan"]))


def _payoff_matrix(request: AuthorityHandlerRequest) -> dict[str, Any]:
    items = _many(request, "promise", "foreshadow_state", "mystery", "relationship_state", "character_state", "world_rule", "reward_ledger", "theme_question", "antagonist_threat")
    rows = list(_payload(request).get("items", []))
    versions = {item.asset_version_id for item in items}
    if any(str(row.get("asset_version_id")) not in versions for row in rows):
        raise ValueError("payoff item must reference a frozen input version")
    return build_payoff_matrix(project_id=request.project_id, items=rows)


def _ending_quality(request: AuthorityHandlerRequest) -> dict[str, Any]:
    closure = _one(request, "closure_plan")
    matrix = _one(request, "payoff_matrix")
    evidence = _one(request, "ending_evidence")
    return evaluate_ending_quality(project_id=request.project_id, closure_plan_version_id=closure.asset_version_id, payoff_matrix=matrix.content, evidence=evidence.content)


def _motivation(request: AuthorityHandlerRequest) -> dict[str, Any]:
    states = _many(request, "character_state")
    behavior = _one(request, "character_behavior")
    return detect_motivation_drift(project_id=request.project_id, character_state_versions=[{"asset_version_id": item.asset_version_id, **item.content} for item in states], current_behavior={"asset_version_id": behavior.asset_version_id, **behavior.content})


def _entity_merge(request: AuthorityHandlerRequest) -> dict[str, Any]:
    entities = _many(request, "entity_identity")
    if len(entities) != 2:
        raise ValueError("entity merge requires exactly two identities")
    mentions = [item.content for item in request.inputs if item.asset_type == "entity_mention"]
    return propose_entity_merge(project_id=request.project_id, left=entities[0].content, right=entities[1].content, mentions=mentions)


def _foreshadow(request: AuthorityHandlerRequest) -> dict[str, Any]:
    thread = _one(request, "foreshadow_state")
    evidence = _one(request, "foreshadow_payoff_evidence")
    return evaluate_foreshadow_payoff(project_id=request.project_id, thread_version_id=thread.asset_version_id, scores=dict(evidence.content["scores"]))


def _world_rule(request: AuthorityHandlerRequest) -> dict[str, Any]:
    rules = _many(request, "world_rule")
    events = [item for item in request.inputs if item.asset_type == "world_event"]
    return detect_world_rule_conflicts(project_id=request.project_id, rule_versions=[{"asset_version_id": item.asset_version_id, **item.content} for item in rules], events=[{"asset_version_id": item.asset_version_id, **item.content} for item in events])


def _power(request: AuthorityHandlerRequest) -> dict[str, Any]:
    states = _many(request, "power_state")
    if len(states) != 2:
        raise ValueError("power evaluation requires previous and current states")
    return detect_power_conflicts(project_id=request.project_id, previous_state={"asset_version_id": states[0].asset_version_id, **states[0].content}, current_state={"asset_version_id": states[1].asset_version_id, **states[1].content})


def _pattern(request: AuthorityHandlerRequest) -> dict[str, Any]:
    rows = _many(request, "narrative_pattern_fingerprint")
    return detect_pattern_repetition(project_id=request.project_id, fingerprints=[item.content for item in rows], threshold=int(_payload(request).get("threshold", 3)))


def _debt(request: AuthorityHandlerRequest) -> dict[str, Any]:
    debts = _many(request, "narrative_debt")
    return evaluate_narrative_debt(project_id=request.project_id, current_chapter=int(_payload(request)["current_chapter"]), debts=[item.content for item in debts])


def _recap(request: AuthorityHandlerRequest) -> dict[str, Any]:
    report_assets = _many(request, "motivation_drift_report", "relationship_report", "canon_conflict_report", "world_rule_conflict_report", "power_conflict_report", "foreshadow_payoff_report", "narrative_debt_report", "reward_cadence_report", "antagonist_pressure_report", "pattern_repetition_report", "theme_movement_report", "quality_score_report")
    reports = dict(_payload(request).get("reports", {}))
    for item in report_assets:
        reports.setdefault(item.asset_type, item.content)
    aliases = {
        "motivation": "motivation_drift_report", "relationships": "relationship_report",
        "canon": "canon_conflict_report", "world_rules": "world_rule_conflict_report",
        "power": "power_conflict_report", "foreshadow": "foreshadow_payoff_report",
        "promise_debt": "narrative_debt_report", "reward_cadence": "reward_cadence_report",
        "antagonist_pressure": "antagonist_pressure_report", "patterns": "pattern_repetition_report",
        "theme": "theme_movement_report", "quality": "quality_score_report",
    }
    for key, asset_type in aliases.items():
        if key not in reports and asset_type in reports:
            reports[key] = reports[asset_type]
    return build_enhanced_recap(project_id=request.project_id, reports=reports)


def _golden_sample_create(request: AuthorityHandlerRequest) -> dict[str, Any]:
    payload = dict(_payload(request)["sample"])
    payload["project_scope"] = request.project_id
    if tuple(payload["input_asset_version_ids"]) != tuple(
        item.asset_version_id for item in request.inputs
    ):
        raise ValueError("golden sample targets must equal its frozen input assets")
    sample = QualityGoldenSample(
        sample_id=str(payload["sample_id"]),
        project_scope=request.project_id,
        dimension=str(payload["dimension"]),
        input_asset_version_ids=tuple(payload["input_asset_version_ids"]),
        expected_status=str(payload["expected_status"]),
        expected_score_range=tuple(payload["expected_score_range"]),
        human_evidence=tuple(payload["human_evidence"]),
        annotator=str(payload["annotator"]),
        adjudication_status=str(payload["adjudication_status"]),
        dataset_version=str(payload["dataset_version"]),
    )
    return {"project_id": request.project_id, **asdict(sample)}


def _human_decision_record(request: AuthorityHandlerRequest) -> dict[str, Any]:
    sample = _one(request, "quality_golden_sample")
    payload = dict(_payload(request)["decision"])
    if str(payload.get("sample_id") or "") != str(sample.content.get("sample_id") or ""):
        raise ValueError("human decision targets another golden sample")
    decision = QualityHumanDecision(
        sample_id=str(payload["sample_id"]), dimension=str(payload["dimension"]),
        status=str(payload["status"]), score=payload.get("score"),
        evidence=tuple(payload.get("evidence") or ()), annotator=str(payload["annotator"]),
    )
    if decision.dimension != sample.content.get("dimension"):
        raise ValueError("human decision dimension differs from its sample")
    return {"project_id": request.project_id, **asdict(decision)}


def _calibration_run(request: AuthorityHandlerRequest) -> dict[str, Any]:
    profile_asset = _one(request, "quality_calibration_profile")
    sample_assets = _many(request, "quality_golden_sample")
    decision_assets = _many(request, "quality_provider_decision")
    profile = _calibration_profile(profile_asset.content)
    payload = _payload(request)
    run = QualityCalibrationRun(
        run_id=str(payload["run_id"]), profile_id=profile.profile_id,
        dimension=profile.dimension, dataset_version=profile.dataset_version,
        provider_decision_asset_version_ids=tuple(
            item.asset_version_id for item in decision_assets
        ),
        sample_ids=tuple(str(item.content["sample_id"]) for item in sample_assets),
    )
    policy_payload = dict(payload["policy"])
    policy = QualityCalibrationPolicy(**policy_payload)
    report = evaluate_calibration_run(
        run=run, profile=profile,
        samples=tuple(_golden_sample(item.content) for item in sample_assets),
        decisions=tuple(
            QualityProviderDecision(
                sample_id=str(item.content["sample_id"]),
                dimension=str(item.content["dimension"]),
                status=str(item.content["status"]),
                score=item.content.get("score"),
                confidence=float(item.content["confidence"]),
                provider_evidence_asset_version_id=item.asset_version_id,
            )
            for item in decision_assets
        ),
        policy=policy,
    )
    return {
        "project_id": request.project_id,
        "profile_asset_version_id": profile_asset.asset_version_id,
        "sample_asset_version_ids": [item.asset_version_id for item in sample_assets],
        "provider_decision_asset_version_ids": [item.asset_version_id for item in decision_assets],
        **asdict(report),
        "calibration_status": report.calibration_status.value,
        "fixture_protocol_only": bool(payload.get("fixture_protocol_only", False)),
        "real_model_call": False,
        "production_verified": False,
    }


def _calibration_profile_promote(request: AuthorityHandlerRequest) -> dict[str, Any]:
    profile_asset = _one(request, "quality_calibration_profile")
    report_asset = _one(request, "quality_calibration_report")
    report_content = report_asset.content
    from novel_forge.modules.chapter_quality_authority.calibration import QualityCalibrationReport

    report = QualityCalibrationReport(
        **{
            key: value for key, value in report_content.items()
            if key in QualityCalibrationReport.__dataclass_fields__
            and key != "calibration_status"
        },
        calibration_status=QualityCalibrationStatus(
            str(report_content["calibration_status"])
        ),
    )
    promoted = promote_calibration_profile(
        profile=_calibration_profile(profile_asset.content), report=report
    )
    return {
        "project_id": request.project_id,
        **asdict(promoted),
        "status": promoted.status.value,
        "promoted_from_asset_version_id": profile_asset.asset_version_id,
        "calibration_report_asset_version_id": report_asset.asset_version_id,
        "production_verified": False,
    }


def _calibration_profile_revoke(request: AuthorityHandlerRequest) -> dict[str, Any]:
    profile_asset = _one(request, "quality_calibration_profile")
    profile = _calibration_profile(profile_asset.content)
    reason = str(_payload(request).get("reason") or "").strip()
    if not reason:
        raise ValueError("calibration revocation reason is required")
    return {
        "project_id": request.project_id,
        **asdict(profile),
        "status": QualityCalibrationStatus.CALIBRATION_REVOKED.value,
        "revoked": True,
        "revocation_reason": reason,
        "revoked_asset_version_id": profile_asset.asset_version_id,
        "production_verified": False,
    }


def _calibration_profile(content: dict[str, Any]) -> QualityCalibrationProfile:
    return QualityCalibrationProfile(
        profile_id=str(content["profile_id"]), dimension=str(content["dimension"]),
        dataset_version=str(content["dataset_version"]),
        threshold_policy_version_id=str(content["threshold_policy_version_id"]),
        status=QualityCalibrationStatus(str(content.get("status") or "UNCALIBRATED")),
        revoked=bool(content.get("revoked")), stale=bool(content.get("stale")),
    )


def _golden_sample(content: dict[str, Any]) -> QualityGoldenSample:
    return QualityGoldenSample(
        sample_id=str(content["sample_id"]), project_scope=str(content["project_scope"]),
        dimension=str(content["dimension"]),
        input_asset_version_ids=tuple(content["input_asset_version_ids"]),
        expected_status=str(content["expected_status"]),
        expected_score_range=tuple(content["expected_score_range"]),
        human_evidence=tuple(content["human_evidence"]), annotator=str(content["annotator"]),
        adjudication_status=str(content["adjudication_status"]),
        dataset_version=str(content["dataset_version"]),
    )


CONTENT_CODECS: dict[str, ContentHandlerCodec] = {
    name: ContentHandlerCodec(name, asset_type, output_key, binder)
    for name, asset_type, output_key, binder in (
        ("creative.brief.create", "creative_brief", "creative.brief", _creative_brief),
        ("creative.candidates.evaluate", "candidate_evaluation", "creative.candidate_evaluation", _creative_evaluate),
        ("creative.candidates.cluster", "candidate_cluster", "creative.candidate_cluster", _creative_cluster),
        ("creative.project.approve", "project_proposal", "creative.project_proposal", _creative_approve),
        ("production.world.generate", "world_bible", "world.bible", _world_generate),
        ("world.validate", "world_rule_conflict_report", "world.validation", _world_validate),
        ("production.character.generate", "character_card", "character.card", _character_generate),
        ("character.relationships.generate", "relationship_state", "character.relationship", _relationships_generate),
        ("theme.question.create", "theme_question", "theme.question", _theme_question),
        ("theme.arc.build", "theme_arc", "theme.arc", _theme_arc),
        ("theme.anti_preaching.evaluate", "anti_preaching_report", "theme.anti_preaching", _anti_preaching),
        ("ending.closure.plan", "closure_plan", "ending.closure", _closure_plan),
        ("ending.payoff_matrix.build", "payoff_matrix", "ending.payoff_matrix", _payoff_matrix),
        ("ending.quality.evaluate", "ending_quality_report", "ending.quality", _ending_quality),
        ("longform.motivation.evaluate", "motivation_drift_report", "longform.motivation", _motivation),
        ("longform.entity_merge.propose", "entity_merge_proposal", "longform.entity_merge", _entity_merge),
        ("longform.foreshadow_payoff.evaluate", "foreshadow_payoff_report", "longform.foreshadow_payoff", _foreshadow),
        ("longform.world_rule.evaluate", "world_rule_conflict_report", "longform.world_rule", _world_rule),
        ("longform.power.evaluate", "power_conflict_report", "longform.power", _power),
        ("longform.pattern.evaluate", "pattern_repetition_report", "longform.pattern", _pattern),
        ("longform.narrative_debt.evaluate", "narrative_debt_report", "longform.narrative_debt", _debt),
        ("longform.recap.enhance", "longform_recap_report", "longform.recap", _recap),
        ("quality.golden_sample.create", "quality_golden_sample", "quality.golden_sample", _golden_sample_create),
        ("quality.human_decision.record", "quality_human_decision", "quality.human_decision", _human_decision_record),
        ("quality.calibration.run", "quality_calibration_report", "quality.calibration_report", _calibration_run),
        ("quality.calibration.profile.promote", "quality_calibration_profile", "quality.calibration.profile", _calibration_profile_promote),
        ("quality.calibration.profile.revoke", "quality_calibration_profile", "quality.calibration.profile_revocation", _calibration_profile_revoke),
    )
}

__all__ = ["CONTENT_CODECS", "ContentHandlerCodec"]
