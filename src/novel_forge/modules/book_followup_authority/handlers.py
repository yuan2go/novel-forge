"""INVARIANT: Storage-free handlers executed by the shared fenced Authority runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from novel_forge.modules.authority_handler_runtime import (
    AuthorityAuxiliaryOutput,
    AuthorityHandlerOutput,
    AuthorityHandlerRequest,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.reader_calibration import JudgeMode
from novel_forge.modules.reader_judge_authority import (
    ReaderJudgeResolutionScope,
    ReaderJudgeRuntimeResolver,
)

from .contracts import ReaderOutcomeModelPort
from .domain import (
    LongformCheckpointType,
    build_longform_recap_outputs,
    evaluate_reader_outcome,
)


@dataclass(frozen=True, slots=True)
class ReaderOutcomeHandler:
    model_port: ReaderOutcomeModelPort
    runtime_resolver: ReaderJudgeRuntimeResolver

    def __post_init__(self) -> None:
        if not bool(getattr(self.model_port, "external_effect_backed", False)):
            raise ValueError(
                "Reader Outcome requires an ExternalEffect-backed model port"
            )

    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        payload = _payload(request)
        required = (
            "book_id",
            "chapter_id",
            "chapter_number",
            "final_draft_asset_version",
            "chapter_plan_asset_version",
            "book_design_version",
            "book_plan_version",
            "parent_plan_versions",
            "reader_segment_version",
            "reader_contract_version",
            "platform_profile_version",
            "canon_snapshot_version",
            "chapter_outcome_version",
            "story_state_version",
            "quality_evidence_version",
            "input_manifest_ref",
            "previous_reader_state_version",
            "evaluation_profile_version",
            "model_strategy_version",
            "context_token_budget",
        )
        missing = [name for name in required if payload.get(name) in (None, "")]
        if missing:
            raise KernelError(
                "READER_OUTCOME_INPUT_INVALID",
                "missing Reader Outcome fields: " + ", ".join(missing),
            )
        try:
            context_token_budget = int(payload["context_token_budget"])
        except (TypeError, ValueError) as exc:
            raise KernelError(
                "READER_OUTCOME_INPUT_INVALID",
                "Reader Outcome context token budget must be an integer",
            ) from exc
        if context_token_budget <= 0:
            raise KernelError(
                "READER_OUTCOME_INPUT_INVALID",
                "Reader Outcome context token budget must be positive",
            )
        try:
            observed_through_chapter = int(
                payload.get("observed_through_chapter") or payload["chapter_number"]
            )
            if observed_through_chapter != int(payload["chapter_number"]):
                raise KernelError(
                    "READER_OUTCOME_ACCEPTED_HEAD_MISMATCH",
                    "Reader Outcome must observe exactly its accepted Chapter head",
                )
        except (TypeError, ValueError) as exc:
            raise KernelError(
                "READER_OUTCOME_INPUT_INVALID",
                "Reader Outcome accepted Chapter head is invalid",
            ) from exc
        declared = tuple(request.command.get("input_asset_version_ids") or ())
        frozen = tuple(item.asset_version_id for item in request.inputs)
        if declared != frozen:
            raise KernelError(
                "READER_OUTCOME_FROZEN_INPUT_MISMATCH",
                "Reader Outcome declared inputs differ from frozen assets",
            )
        judge = self.runtime_resolver.resolve(
            ReaderJudgeResolutionScope(
                project_id=request.project_id,
                book_id=str(payload["book_id"]),
                platform=str(
                    payload.get("platform") or payload["platform_profile_version"]
                ),
                genre=str(payload.get("genre") or "*"),
                subgenre=str(payload.get("subgenre") or "*"),
                chapter_type=str(payload.get("chapter_type") or "STANDARD"),
                reader_segment=str(
                    payload.get("reader_segment") or payload["reader_segment_version"]
                ),
                model_version=str(payload["model_strategy_version"]),
            )
        )
        result = self.model_port.invoke(
            request,
            stage="reader_outcome",
            payload={
                "chapter": int(payload["chapter_number"]),
                "book_id": str(payload["book_id"]),
                "reader_contract_version": str(payload["reader_contract_version"]),
                "evaluation_profile_version": str(
                    payload["evaluation_profile_version"]
                ),
                "reader_judge_execution_snapshot": judge.to_dict(),
            },
            reservation_tokens=context_token_budget,
        )
        raw_state = result.output.get("reader_state")
        raw_evidence = result.output.get("evidence")
        if not isinstance(raw_state, dict) or not isinstance(raw_evidence, list):
            raise KernelError(
                "MODEL_RESPONSE_INVALID",
                "Reader Outcome response requires reader_state and evidence",
            )
        decision = evaluate_reader_outcome(raw_state, evidence=raw_evidence)
        source_refs = tuple(item.asset_version_id for item in request.inputs)
        common_evidence = {
            "evidence_class": "READER_PROXY_ADVISORY",
            "provider": result.provider_id,
            "model": result.model_id,
            "prompt_version": result.prompt_version,
            "skill_version": result.skill_version,
            "real_model_call": result.real_model_call,
            "execution": dict(result.execution_evidence or {}),
            "accepted_input_lineage": {
                "observed_through_chapter": observed_through_chapter,
                "acceptance_operation_id": str(
                    payload.get("acceptance_operation_id") or ""
                ),
                "book_production_input_snapshot_id": str(
                    payload.get("book_production_input_snapshot_id") or ""
                ),
                "lineage_completeness": (
                    "COMPLETE"
                    if payload.get("acceptance_operation_id")
                    and payload.get("book_production_input_snapshot_id")
                    else "LEGACY_PARTIAL"
                ),
                "accepted_chapter_outcome_version": str(
                    payload["chapter_outcome_version"]
                ),
                "accepted_story_state_version": str(payload["story_state_version"]),
                "accepted_canon_snapshot_version": str(
                    payload["canon_snapshot_version"]
                ),
            },
        }
        execution = dict(result.execution_evidence or {})
        execution_result = dict(execution.get("execution_result") or {})
        route_snapshot = dict(execution.get("route_snapshot") or {})
        continue_intent = float(decision["reader_state"]["continue_intent"])
        ordinal_band = (
            "HIGH"
            if continue_intent >= 0.7
            else "MEDIUM"
            if continue_intent >= 0.4
            else "LOW"
        )
        report = {
            "type": "ReaderOutcomeReport",
            "contract_version": "reader-outcome-report-v1",
            "evidence_class": "READER_PROXY_ADVISORY",
            "project_id": request.project_id,
            "book_id": str(payload["book_id"]),
            "chapter_id": str(payload["chapter_id"]),
            "chapter_number": int(payload["chapter_number"]),
            "observed_through_chapter": observed_through_chapter,
            "accepted_input_lineage": dict(common_evidence["accepted_input_lineage"]),
            **decision,
            "source_asset_versions": list(source_refs),
            "model_evidence": result.to_evidence(),
            "body_mutation_allowed": False,
            "reader_judge_execution_snapshot": judge.to_dict(),
            "mode": judge.mode.value,
            "judge_qualification_status": judge.calibration_status.value,
            "calibration_status": judge.calibration_label,
            "score_semantics": judge.score_semantics,
            "publish_blocking": judge.publish_blocking,
            "confidence": 0.0,
            "confidence_status": "NOT_MEASURED",
            "judge_profile_version": str(payload["evaluation_profile_version"]),
            "target_asset_version_id": str(payload["final_draft_asset_version"]),
            "reader_segment_version": str(payload.get("reader_segment_version") or ""),
            "input_manifest_ref": str(
                payload.get("input_manifest_ref")
                or (execution.get("input_manifest") or {}).get("input_manifest_id")
                or ""
            ),
            "route_snapshot_id": str(route_snapshot.get("route_snapshot_id") or ""),
            "raw_scores": dict(decision["reader_state"]),
            "ordinal_band": ordinal_band,
            "evidence_spans": [dict(item) for item in raw_evidence],
            "disagreement": {"status": "NOT_MEASURED"},
            "position_sensitivity": {"status": "NOT_MEASURED"},
            "ood_status": "NOT_EVALUATED",
            "mutation_stability": {"status": "NOT_MEASURED"},
            "canon_mutation_allowed": False,
            "future_intent_actualization_allowed": False,
            "direct_plan_activation_allowed": False,
            "usage_receipt_ref": str(execution_result.get("usage_receipt_ref") or ""),
            "cost_receipt_ref": str(execution_result.get("cost_receipt_ref") or ""),
        }
        auxiliaries = [
            AuthorityAuxiliaryOutput(
                asset_type="reader_state_transition",
                output_key="reader_outcome.state_transition",
                role="reader_state",
                content={
                    "type": "ReaderStateTransition",
                    "contract_version": "reader-state-transition-v1",
                    "evidence_class": "READER_PROXY_ADVISORY",
                    "previous_reader_state_version": str(
                        payload["previous_reader_state_version"]
                    ),
                    "reader_state": decision["reader_state"],
                    "gate": decision["gate"],
                    "candidate_status": f"{judge.mode.value}_CANDIDATE",
                    "judge_qualification_status": judge.calibration_status.value,
                    "calibration_status": judge.calibration_label,
                    "score_semantics": judge.score_semantics,
                    "authority_commit_allowed": judge.authority_commit_allowed,
                    "canon_mutation_allowed": False,
                    "future_intent_actualization_allowed": False,
                },
                qualification_policy="reader-outcome-output-v1",
                reference_asset_version_ids=source_refs,
                evidence=common_evidence,
            ),
            AuthorityAuxiliaryOutput(
                asset_type="reader_issue_set",
                output_key="reader_outcome.issue_set",
                role="issues",
                content={
                    "type": "ReaderIssueSet",
                    "contract_version": "reader-issue-set-v1",
                    "evidence_class": "READER_PROXY_ADVISORY",
                    "issues": decision["issues"],
                    "gate": decision["gate"],
                },
                qualification_policy="reader-outcome-output-v1",
                reference_asset_version_ids=source_refs,
                evidence=common_evidence,
            ),
        ]
        if (
            judge.mode is JudgeMode.BOUNDED_PRODUCTION
            and judge.plan_adjustment_candidate_allowed
            and decision["gate"]
            in {
                "REVISION_REQUIRED",
                "REVISION_RECOMMENDED",
                "HUMAN_REVIEW_REQUIRED",
            }
        ):
            chapter = int(payload["chapter_number"])
            auxiliaries.append(
                AuthorityAuxiliaryOutput(
                    asset_type="reader_plan_adjustment_candidate",
                    output_key="reader_outcome.plan_adjustment_candidate",
                    role="plan_adjustment_candidate",
                    content={
                        "type": "ReaderPlanAdjustmentCandidate",
                        "contract_version": "reader-plan-adjustment-candidate-v1",
                        "evidence_class": "READER_PROXY_ADVISORY",
                        "book_id": str(payload["book_id"]),
                        "source_chapter": chapter,
                        "affected_chapter_range": [
                            chapter + 1,
                            chapter + judge.maximum_adjustment_chapters,
                        ],
                        "maximum_adjustment_chapters": judge.maximum_adjustment_chapters,
                        "target_scope": "FUTURE_ONLY",
                        "candidate_only": True,
                        "plan_change_activation_required": True,
                        "activation_allowed": False,
                        "required_authority": "PLAN_CHANGE_AUTHORITY",
                        "body_mutation_allowed": False,
                        "executed_plan_mutation_allowed": False,
                        "ending_mutation_allowed": False,
                        "issues": decision["issues"],
                        "judge_snapshot_id": judge.snapshot_id,
                    },
                    qualification_policy="reader-bounded-adjustment-v1",
                    reference_asset_version_ids=source_refs,
                    evidence=common_evidence,
                )
            )
        return AuthorityHandlerOutput(
            asset_type="reader_outcome_report",
            output_key="reader_outcome.report",
            role="primary",
            content=report,
            qualification_policy="reader-outcome-output-v1",
            reference_asset_version_ids=source_refs,
            evidence=common_evidence,
            auxiliary_outputs=tuple(auxiliaries),
        )


class LongformRecapHandler:
    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        payload = _payload(request)
        required = (
            "book_id",
            "checkpoint_type",
            "chapter_range",
            "book_design_version",
            "book_plan_version",
            "volume_plan_version",
            "arc_plan_versions",
            "canon_snapshot_version",
            "story_state_version",
            "reader_state_version",
            "quality_trend_version",
            "chapter_outcome_versions",
        )
        missing = [name for name in required if payload.get(name) in (None, "")]
        if missing:
            raise KernelError(
                "LONGFORM_RECAP_INPUT_INVALID",
                "missing Long-form Recap fields: " + ", ".join(missing),
            )
        arc_plan_versions = payload.get("arc_plan_versions")
        if (
            not isinstance(arc_plan_versions, list)
            or not arc_plan_versions
            or any(not isinstance(item, str) or not item for item in arc_plan_versions)
            or len(set(arc_plan_versions)) != len(arc_plan_versions)
        ):
            raise KernelError(
                "LONGFORM_RECAP_INPUT_INVALID",
                "Long-form Recap requires one ordered, unique current Arc set",
            )
        try:
            checkpoint_type = LongformCheckpointType(str(payload["checkpoint_type"]))
            chapter_range = tuple(int(value) for value in payload["chapter_range"])
        except (TypeError, ValueError) as exc:
            raise KernelError(
                "LONGFORM_RECAP_INPUT_INVALID",
                "Long-form checkpoint or chapter range is invalid",
            ) from exc
        if len(chapter_range) != 2:
            raise KernelError(
                "LONGFORM_RECAP_INPUT_INVALID", "chapter_range must have two boundaries"
            )
        try:
            observed_through_chapter = int(
                payload.get("observed_through_chapter") or chapter_range[1]
            )
        except (TypeError, ValueError) as exc:
            raise KernelError(
                "LONGFORM_RECAP_INPUT_INVALID",
                "Long-form Recap accepted Chapter head is invalid",
            ) from exc
        chapter_outcome_versions = payload.get("chapter_outcome_versions")
        if (
            observed_through_chapter != chapter_range[1]
            or not isinstance(chapter_outcome_versions, list)
            or not chapter_outcome_versions
            or any(
                not isinstance(item, str) or not item
                for item in chapter_outcome_versions
            )
        ):
            raise KernelError(
                "LONGFORM_RECAP_ACCEPTED_HEAD_MISMATCH",
                "Long-form Recap must retain its accepted observation head and outcomes",
            )
        declared = tuple(request.command.get("input_asset_version_ids") or ())
        frozen = tuple(item.asset_version_id for item in request.inputs)
        if declared != frozen:
            raise KernelError(
                "LONGFORM_RECAP_FROZEN_INPUT_MISMATCH",
                "Long-form Recap declared inputs differ from frozen assets",
            )
        source_refs = tuple(item.asset_version_id for item in request.inputs)
        outputs = build_longform_recap_outputs(
            project_id=request.project_id,
            book_id=str(payload["book_id"]),
            chapter_range=(chapter_range[0], chapter_range[1]),
            checkpoint_type=checkpoint_type,
            observations=dict(payload.get("observations") or {}),
        )
        accepted_input_lineage = {
            "observed_through_chapter": observed_through_chapter,
            "acceptance_operation_id": str(
                payload.get("acceptance_operation_id") or ""
            ),
            "book_production_input_snapshot_id": str(
                payload.get("book_production_input_snapshot_id") or ""
            ),
            "lineage_completeness": (
                "COMPLETE"
                if payload.get("acceptance_operation_id")
                and payload.get("book_production_input_snapshot_id")
                else "LEGACY_PARTIAL"
            ),
            "book_design_version": str(payload["book_design_version"]),
            "book_plan_version": str(payload["book_plan_version"]),
            "volume_plan_version": str(payload["volume_plan_version"]),
            "arc_plan_versions": list(payload["arc_plan_versions"]),
            "accepted_chapter_outcome_versions": list(
                payload.get("chapter_outcome_versions") or ()
            ),
            "accepted_story_state_version": str(payload["story_state_version"]),
            "accepted_canon_snapshot_version": str(payload["canon_snapshot_version"]),
        }
        for output in outputs.values():
            if isinstance(output, dict):
                output["observed_through_chapter"] = observed_through_chapter
                output["accepted_input_lineage"] = dict(accepted_input_lineage)
        auxiliaries = [
            AuthorityAuxiliaryOutput(
                asset_type="longform_deviation_report",
                output_key="longform.recap.deviation_report",
                role="deviations",
                content=outputs["deviation_report"],
                qualification_policy="longform-recap-output-v1",
                reference_asset_version_ids=source_refs,
                evidence={
                    "handler": "deterministic-longform-recap-v1",
                    "accepted_input_lineage": accepted_input_lineage,
                },
            ),
            AuthorityAuxiliaryOutput(
                asset_type="plan_adjustment_proposal",
                output_key="longform.recap.adjustment_proposal",
                role="proposal",
                content=outputs["adjustment_proposal"],
                qualification_policy="longform-recap-output-v1",
                reference_asset_version_ids=source_refs,
                evidence={
                    "authority_decision_required": True,
                    "accepted_input_lineage": accepted_input_lineage,
                },
            ),
        ]
        if outputs["replan_request"] is not None:
            auxiliaries.append(
                AuthorityAuxiliaryOutput(
                    asset_type=(
                        "arc_revision_candidate"
                        if outputs["replan_request"].get("type")
                        == "ArcRevisionCandidate"
                        else "replan_request"
                    ),
                    output_key="longform.recap.replan_request",
                    role="proposal",
                    content=outputs["replan_request"],
                    qualification_policy="longform-recap-output-v1",
                    reference_asset_version_ids=source_refs,
                    evidence={
                        "authority_decision_required": True,
                        "accepted_input_lineage": accepted_input_lineage,
                    },
                )
            )
        return AuthorityHandlerOutput(
            asset_type="longform_recap",
            output_key="longform.recap.report",
            role="primary",
            content=outputs["recap"],
            qualification_policy="longform-recap-output-v1",
            reference_asset_version_ids=source_refs,
            evidence={
                "handler": "deterministic-longform-recap-v1",
                "plan_mutation_allowed": False,
                "accepted_input_lineage": accepted_input_lineage,
            },
            auxiliary_outputs=tuple(auxiliaries),
        )


def _payload(request: AuthorityHandlerRequest) -> dict[str, Any]:
    payload = request.command.get("payload")
    if not isinstance(payload, dict):
        raise KernelError("BOOK_FOLLOWUP_INPUT_INVALID", "payload must be an object")
    return payload


__all__ = ["LongformRecapHandler", "ReaderOutcomeHandler"]
