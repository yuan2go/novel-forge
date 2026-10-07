from __future__ import annotations

from novel_forge.modules.authority_handler_runtime import (
    AuthorityAuxiliaryOutput,
    AuthorityHandlerOutput,
    AuthorityHandlerRequest,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state import materialize_canon_snapshot_v2

from .contracts import CHAPTER_OUTCOME_DEFINITION_VERSION
from .domain import build_chapter_outcome, reduce_story_state


class ChapterOutcomeCommitHandler:
    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        payload = request.command.get("payload")
        if not isinstance(payload, dict):
            raise KernelError(
                "CHAPTER_OUTCOME_INPUT_INVALID", "payload must be an object"
            )
        required_types = (
            "chapter_plan",
            "best_draft_candidate",
            "re_review_report",
            "canon_patch",
            "quality_score_report",
            "release_package",
            "final_release_gate_report",
        )
        inputs = {
            asset_type: request.require_input(asset_type)
            for asset_type in required_types
        }
        final_gate = inputs["final_release_gate_report"].content
        quality = inputs["quality_score_report"].content
        rereview = inputs["re_review_report"].content
        release = inputs["release_package"].content
        canon = inputs["canon_patch"].content
        chapter_plan = inputs["chapter_plan"].content
        validation = quality.get("internal_admission")
        internal = (isinstance(validation, dict) and validation.get("status") == "INTERNAL_ADMITTED"
            and validation.get("version") in {"creative-quality-admission.v1", "creative-quality-admission.v2"}
            and validation.get("book_id") == payload["book_id"]
            and validation.get("target_asset_version_id") == inputs["best_draft_candidate"].asset_version_id
            and validation == final_gate.get("internal_admission")
            and final_gate.get("final_gate_contract_version") == "creative-internal-finalize.v1"
            and final_gate.get("gate") == "INTERNAL_ADMITTED"
            and final_gate.get("release_status") == "INTERNAL_VALIDATION_FINALIZED")
        if (
            not internal and (final_gate.get("gate") != "PASSED"
                or final_gate.get("release_status") != "INTERNAL_RELEASE_FINALIZED"
                or quality.get("gate") not in {"PASSED", "PASSED_WITH_UNCALIBRATED"})
            or rereview.get("decision") != "PASSED"
            or int(rereview.get("blocking_issue_count", 0)) != 0
            or release.get("release_status") != "READY_FOR_BLOB_VERIFICATION"
        ):
            raise KernelError(
                "CHAPTER_ACCEPTANCE_EVIDENCE_BLOCKED",
                "Chapter release, review, or quality evidence is incomplete",
            )
        if canon.get("grounding"):
            from novel_forge.modules.chapter_outcome.acceptance_contract import require_grounded_acceptance
            require_grounded_acceptance(project_id=request.project_id, selected={
                key: {"asset_version_id": item.asset_version_id, "content": item.content}
                for key, item in inputs.items()
            })
        source_refs = tuple(item.asset_version_id for item in request.inputs)
        outcome = build_chapter_outcome(
            project_id=request.project_id,
            book_id=str(payload["book_id"]),
            chapter_number=int(payload["chapter_number"]),
            chapter_plan_version_id=inputs["chapter_plan"].asset_version_id,
            parent_group_version_id=str(payload.get("parent_group_version_id") or ""),
            accepted_draft_version_id=inputs["best_draft_candidate"].asset_version_id,
            final_release_gate_version_id=inputs[
                "final_release_gate_report"
            ].asset_version_id,
            quality_aggregate_version_id=inputs[
                "quality_score_report"
            ].asset_version_id,
            canon_patch_asset_version_id=inputs["canon_patch"].asset_version_id,
            canon_patch=canon,
            cost_receipt_refs=tuple(payload.get("cost_receipt_refs") or ()),
            created_by_operation_id=request.operation_id,
            trace_id=request.trace_id,
            work_requirements=request.definition_version == CHAPTER_OUTCOME_DEFINITION_VERSION,
            expected_arc_contributions=tuple(
                dict(item)
                for item in (
                    (
                        (chapter_plan.get("constraint_envelope") or {})
                        .get("arc_working_set", {})
                        .get("selected_contributions")
                        if isinstance(chapter_plan.get("constraint_envelope"), dict)
                        else None
                    )
                    or chapter_plan.get("required_arc_contributions")
                    or ()
                )
                if isinstance(item, dict)
            ),
        )
        outcome_version_id = (
            f"authority-output:{request.operation_id}:chapter.outcome:v1"
        )
        previous = request.inputs_of_type("story_state_snapshot")
        if len(previous) > 1:
            raise KernelError(
                "CHAPTER_OUTCOME_INPUT_INVALID",
                "only one previous Story State snapshot is allowed",
            )
        state = reduce_story_state(
            previous=previous[0].content if previous else None,
            chapter_outcome=outcome,
            chapter_outcome_asset_version_id=outcome_version_id,
            previous_story_state_asset_version_id=(
                previous[0].asset_version_id if previous else ""
            ),
        )
        previous_canon = request.inputs_of_type("canon_snapshot")
        if len(previous_canon) > 1:
            raise KernelError(
                "CHAPTER_OUTCOME_INPUT_INVALID",
                "only one previous Canon snapshot is allowed",
            )
        canon_snapshot = materialize_canon_snapshot_v2(
            story_state=state,
            chapter_outcome_asset_version_id=outcome_version_id,
            previous_canon_asset_version_id=(
                previous_canon[0].asset_version_id if previous_canon else ""
            ),
        )
        evidence = {
            "deterministic": True,
            "model_calls": 0,
            "acceptance_operation_id": request.operation_id,
            "final_release_gate_version_id": inputs[
                "final_release_gate_report"
            ].asset_version_id,
        }
        return AuthorityHandlerOutput(
            asset_type="chapter_outcome",
            output_key="chapter.outcome",
            role="primary",
            content=outcome,
            qualification_policy="chapter-outcome-acceptance-v4" if request.definition_version == CHAPTER_OUTCOME_DEFINITION_VERSION else "chapter-outcome-acceptance-v3",
            reference_asset_version_ids=source_refs,
            evidence=evidence,
            auxiliary_outputs=(
                AuthorityAuxiliaryOutput(
                    asset_type="story_state_snapshot",
                    output_key="chapter.story_state",
                    role="story_state",
                    content=state,
                    qualification_policy="deterministic-story-state-v2",
                    reference_asset_version_ids=source_refs,
                    evidence=evidence,
                ),
                AuthorityAuxiliaryOutput(
                    asset_type="canon_snapshot",
                    output_key="chapter.canon.current",
                    role="canon_truth",
                    content=canon_snapshot,
                    qualification_policy="accepted-canon-snapshot-v2",
                    reference_asset_version_ids=source_refs,
                    evidence=evidence,
                ),
            ),
        )


__all__ = ["ChapterOutcomeCommitHandler"]
