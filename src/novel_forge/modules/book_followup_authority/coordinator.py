"""Durable admission coordinator for non-blocking post-acceptance work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_authority.production import (
    PostgresBookAuthority,
    select_chapter_acceptance_outputs,
)
from novel_forge.modules.book_authority.queries import (
    BookFollowupAdmissionCandidate,
    PostgresBookProductionQuery,
)
from novel_forge.modules.book_followup_authority.application import (
    BookFollowupAdmission,
)
from novel_forge.modules.book_followup_authority.domain import (
    should_trigger_longform_recap,
)
from novel_forge.modules.command_kernel.errors import KernelError


@dataclass(frozen=True, slots=True)
class BookFollowupCoordinationResult:
    book_run_id: str
    chapter_request_id: str
    chapter_number: int
    action: str
    operation_id: str


class PostgresBookFollowupCoordinator:
    """Admit advisory operations from immutable Chapter acceptance evidence.

    Execution remains owned by the shared Command Kernel/Attempt scheduler. This
    coordinator only discovers missing admissions and freezes their domain input.
    It never advances the Book cursor or changes a production-critical state.
    """

    def __init__(
        self,
        authority: PostgresBookAuthority,
        *,
        query: PostgresBookProductionQuery,
        principal: Principal,
    ) -> None:
        self.authority = authority
        self.query = query
        self.principal = principal

    def admission_candidates(
        self, *, limit: int
    ) -> tuple[BookFollowupAdmissionCandidate, ...]:
        return self.query.followup_admission_candidates(limit=limit)

    def admit(
        self, candidate: BookFollowupAdmissionCandidate
    ) -> BookFollowupCoordinationResult:
        snapshot = self.query.require_accepted_followup_snapshot(
            chapter_request_id=candidate.chapter_request_id
        )
        if (
            snapshot["book_run_id"] != candidate.book_run_id
            or snapshot["project_id"] != candidate.project_id
            or int(snapshot["chapter_number"]) != candidate.chapter_number
        ):
            raise KernelError(
                "BOOK_FOLLOWUP_CANDIDATE_DRIFT",
                "follow-up candidate differs from its accepted snapshot",
            )
        if not candidate.reader_operation_id:
            admission = self._schedule_reader(snapshot)
            return self._result(candidate, "ADMIT_READER_OUTCOME", admission)
        if candidate.reader_status != "SUCCEEDED":
            raise KernelError(
                "BOOK_FOLLOWUP_READER_NOT_READY",
                "Longform Recap admission requires a successful Reader Outcome",
            )
        if candidate.recap_operation_id:
            return BookFollowupCoordinationResult(
                candidate.book_run_id,
                candidate.chapter_request_id,
                candidate.chapter_number,
                "NO_ACTION",
                candidate.recap_operation_id,
            )
        reader = self.query.require_followup_output(
            operation_id=candidate.reader_operation_id,
            project_id=candidate.project_id,
            output_key="reader_outcome.report",
        )
        ending_reachability = self.query.ending_reachability(
            book_run_id=candidate.book_run_id,
            chapter_number=candidate.chapter_number,
        )
        trigger = should_trigger_longform_recap(
            chapter_number=candidate.chapter_number,
            light_cadence=int(snapshot["light_recap_cadence"]),
            formal_cadence=int(snapshot["formal_recap_cadence"]),
            chapter_group_complete=self._chapter_group_complete(snapshot),
            authority_requested=bool(ending_reachability.get("replan_required")),
        )
        if not trigger["should_trigger"]:
            raise KernelError(
                "BOOK_FOLLOWUP_RECAP_NOT_DUE",
                "candidate does not carry a governed Longform Recap trigger",
            )
        admission = self._schedule_recap(
            snapshot=snapshot,
            reader=reader,
            trigger=trigger,
            ending_reachability=ending_reachability,
        )
        return self._result(candidate, "ADMIT_LONGFORM_RECAP", admission)

    def _schedule_reader(self, snapshot: dict[str, Any]) -> BookFollowupAdmission:
        evidence = self.authority.chapter_port.require_acceptance_evidence(
            project_id=str(snapshot["project_id"]),
            root_operation_id=str(snapshot["chapter_root_operation_id"]),
        )
        draft = self._evidence_output(evidence, "draft_version")
        quality = self._evidence_output(evidence, "quality_score_report")
        manifest = self._evidence_output(evidence, "production_input_manifest")
        canon = self.authority.resolve_asset_refs(
            project_id=str(snapshot["project_id"]),
            asset_version_ids=(str(snapshot["accepted_canon_snapshot_version"]),),
        )[0]
        arc_plan_versions = tuple(str(item) for item in snapshot["arc_plan_versions"])
        authority_inputs = self.authority.resolve_asset_refs(
            project_id=str(snapshot["project_id"]),
            asset_version_ids=(
                str(snapshot["chapter_plan_version"]),
                str(snapshot["book_design_version"]),
                str(snapshot["book_plan_version"]),
                str(snapshot["volume_plan_version"]),
                *arc_plan_versions,
                str(snapshot["reader_segment_version"]),
                str(snapshot["reader_contract_version"]),
                str(snapshot["platform_profile_version"]),
                str(snapshot["accepted_chapter_outcome_version"]),
                str(snapshot["accepted_story_state_version"]),
            ),
        )
        return self.authority.schedule_reader_outcome(
            str(snapshot["chapter_request_id"]),
            principal=self.principal,
            payload={
                "book_id": snapshot["book_id"],
                "chapter_id": f"chapter:{snapshot['chapter_number']}",
                "chapter_number": int(snapshot["chapter_number"]),
                "observed_through_chapter": int(
                    snapshot["observed_through_chapter"]
                ),
                "acceptance_operation_id": snapshot["acceptance_operation_id"],
                "book_production_input_snapshot_id": snapshot[
                    "book_production_input_snapshot_id"
                ],
                "final_draft_asset_version": draft["asset_version_id"],
                "chapter_plan_asset_version": snapshot["chapter_plan_version"],
                "book_design_version": snapshot["book_design_version"],
                "book_plan_version": snapshot["book_plan_version"],
                "parent_plan_versions": {
                    "volume_plan_version": snapshot["volume_plan_version"],
                    "arc_plan_versions": list(arc_plan_versions),
                },
                "reader_segment_version": snapshot["reader_segment_version"],
                "reader_contract_version": snapshot["reader_contract_version"],
                "platform_profile_version": snapshot["platform_profile_version"],
                "canon_snapshot_version": snapshot[
                    "accepted_canon_snapshot_version"
                ],
                "chapter_outcome_version": snapshot[
                    "accepted_chapter_outcome_version"
                ],
                "story_state_version": snapshot["accepted_story_state_version"],
                "quality_evidence_version": quality["asset_version_id"],
                "input_manifest_ref": manifest["asset_version_id"],
                "previous_reader_state_version": self.query.previous_reader_state(
                    book_run_id=str(snapshot["book_run_id"]),
                    chapter_number=int(snapshot["chapter_number"]),
                ),
                "evaluation_profile_version": "reader-evaluation:v1",
                "model_strategy_version": snapshot["production_profile_version"],
            },
            input_assets=(
                self._asset_ref(draft),
                self._asset_ref(canon),
                self._asset_ref(quality),
                self._asset_ref(manifest),
                *authority_inputs,
            ),
        )

    def _schedule_recap(
        self,
        *,
        snapshot: dict[str, Any],
        reader: dict[str, Any],
        trigger: dict[str, Any],
        ending_reachability: dict[str, Any],
    ) -> BookFollowupAdmission:
        chapter = int(snapshot["chapter_number"])
        arc_plan_versions = tuple(str(item) for item in snapshot["arc_plan_versions"])
        authority_inputs = self.authority.resolve_asset_refs(
            project_id=str(snapshot["project_id"]),
            asset_version_ids=(
                str(snapshot["book_design_version"]),
                str(snapshot["book_plan_version"]),
                str(snapshot["volume_plan_version"]),
                *arc_plan_versions,
                str(snapshot["quality_trend_version"]),
                str(snapshot["accepted_chapter_outcome_version"]),
                str(snapshot["accepted_story_state_version"]),
                str(snapshot["accepted_canon_snapshot_version"]),
            ),
        )
        return self.authority.schedule_longform_recap(
            str(snapshot["chapter_request_id"]),
            principal=self.principal,
            payload={
                "book_id": snapshot["book_id"],
                "checkpoint_type": trigger["checkpoint_type"],
                "chapter_range": [
                    max(
                        1,
                        chapter - int(snapshot["formal_recap_cadence"]) + 1,
                    ),
                    chapter,
                ],
                "observed_through_chapter": int(
                    snapshot["observed_through_chapter"]
                ),
                "acceptance_operation_id": snapshot["acceptance_operation_id"],
                "book_production_input_snapshot_id": snapshot[
                    "book_production_input_snapshot_id"
                ],
                "book_design_version": snapshot["book_design_version"],
                "book_plan_version": snapshot["book_plan_version"],
                "volume_plan_version": snapshot["volume_plan_version"],
                "arc_plan_versions": list(arc_plan_versions),
                "canon_snapshot_version": snapshot[
                    "accepted_canon_snapshot_version"
                ],
                "story_state_version": snapshot["accepted_story_state_version"],
                "reader_state_version": reader["asset_version_id"],
                "quality_trend_version": snapshot["quality_trend_version"],
                "chapter_outcome_versions": [
                    snapshot["accepted_chapter_outcome_version"]
                ],
                "observations": {
                    "reader_state": dict(reader["content"].get("reader_state") or {}),
                    "reader_qualification": {
                        "qualification_status": str(
                            reader["content"].get("judge_qualification_status")
                            or "SHADOW"
                        ),
                        "sample_size": int(reader["content"].get("sample_size") or 0),
                        "confidence": float(reader["content"].get("confidence") or 0),
                        "disagreement": True,
                        "position_bias": True,
                        "ood": True,
                        "drift_detected": False,
                        "recent_reports": [],
                        "last_adjustment_chapter": None,
                    },
                    "canon": {"conflicts": []},
                    "quality_trend": {"direction": "STABLE"},
                    "ending_reachability": ending_reachability,
                },
            },
            input_assets=(
                {
                    "asset_version_id": reader["asset_version_id"],
                    "content_hash": reader["content_hash"],
                },
                *authority_inputs,
            ),
        )

    def _chapter_group_complete(self, snapshot: dict[str, Any]) -> bool:
        group_version = str(snapshot.get("chapter_group_plan_version") or "")
        if not group_version:
            return False
        _start, end = self.query.require_chapter_group_range(group_version)
        return int(snapshot["chapter_number"]) == end

    @staticmethod
    def _evidence_output(evidence: dict[str, Any], asset_type: str) -> dict[str, Any]:
        accepted = select_chapter_acceptance_outputs(evidence)
        if asset_type in accepted:
            return accepted[asset_type]
        matches = [
            item for item in evidence["outputs"] if item["asset_type"] == asset_type
        ]
        if len(matches) != 1:
            raise KernelError(
                "BOOK_CHAPTER_OUTPUT_MISSING",
                f"Chapter Authority produced {len(matches)} {asset_type} outputs",
            )
        return matches[0]

    @staticmethod
    def _asset_ref(item: dict[str, Any]) -> dict[str, str]:
        return {
            "asset_version_id": str(item["asset_version_id"]),
            "content_hash": str(item["content_hash"]),
        }

    @staticmethod
    def _result(
        candidate: BookFollowupAdmissionCandidate,
        action: str,
        admission: BookFollowupAdmission,
    ) -> BookFollowupCoordinationResult:
        return BookFollowupCoordinationResult(
            candidate.book_run_id,
            candidate.chapter_request_id,
            candidate.chapter_number,
            action,
            admission.operation_id,
        )


__all__ = [
    "BookFollowupCoordinationResult",
    "PostgresBookFollowupCoordinator",
]
