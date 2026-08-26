"""PostgreSQL adapter for the exact two-by-four Quality campaign.

The adapter coordinates existing Authorities. It does not own Chapter truth,
Provider effects, Reader state, Canon, plans, or human decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, Mapping, Sequence

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_followup_authority.application import (
    BookFollowupAdmission,
)
from novel_forge.modules.book_followup_authority.coordinator import (
    PostgresBookFollowupCoordinator,
)
from novel_forge.modules.chapter_authority import ChapterNode
from novel_forge.modules.chapter_quality_authority import (
    EvidenceLayer,
    EvidenceSeverity,
    EvidenceStatus,
    PostgresQualityQualificationAuthority,
    QualityArtifactMaterializationCommand,
    QualityEvidenceBindingCommand,
    QualitySubjectBindingCommand,
    build_arc_quality_evaluation,
    build_longitudinal_quality_evidence,
    build_volume_slice_quality_evaluation,
    load_accepted_quality_observations,
)
from novel_forge.modules.reader_calibration import (
    BlindComparisonSubject,
    BlindEvaluator,
    BlindScope,
    EvaluatorIdentityClass,
    export_blind_evaluation_packs,
)
from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.workers.book_authority import (
    execute_book_coordination_claim,
    schedule_book_coordination_jobs,
)

from .quality_campaign import (
    BoundedQualityCampaignProfile,
    QUALITY_CHAPTERS,
    QualityCampaignTerminalError,
    semantic_quality_evidence_identity,
)


@dataclass(frozen=True, slots=True)
class HumanReviewerTarget:
    reviewer_id: str
    identity_class: EvaluatorIdentityClass


@dataclass(frozen=True, slots=True)
class _CandidatePair:
    chapter_number: int
    subject_id: str
    baseline_asset_version_id: str
    baseline_content_hash: str
    baseline_text: str
    canonical_asset_version_id: str
    canonical_content_hash: str
    canonical_text: str
    chapter_plan_asset_version_id: str
    narrative_realization_asset_version_id: str
    accepted_outcome_asset_version_id: str


class PostgresBoundedQualityCampaignRuntime:
    """Drive one already-started bounded campaign through Canonical Runtime."""

    def __init__(
        self,
        *,
        database_url: str,
        profile: BoundedQualityCampaignProfile,
        campaign_id: str,
        book_run_id: str,
        project_id: str,
        workspace_id: str,
        book_id: str,
        primary_arc_plan_version_id: str,
        volume_scope_id: str,
        composition: Any,
        chapter_application: Any,
        operator: Principal,
        chapter_worker: Principal,
        quality_authority: PostgresQualityQualificationAuthority,
        reviewers: Sequence[HumanReviewerTarget],
        campaign_secret: str,
        mode: str,
        book_worker_id: str = "bounded-quality-book-worker",
        failure_injector: Callable[[str], None] | None = None,
    ) -> None:
        if (
            not database_url
            or not campaign_id
            or not book_run_id
            or not project_id
            or not workspace_id
            or not book_id
            or not primary_arc_plan_version_id
            or not volume_scope_id
            or len(reviewers) != 2
            or len({item.reviewer_id for item in reviewers}) != 2
            or len(campaign_secret) < 8
            or mode not in {"scripted", "real"}
        ):
            raise ValueError("bounded PostgreSQL campaign runtime is incomplete")
        self.database_url = database_url
        self.profile = profile
        self.campaign_id = campaign_id
        self.book_run_id = book_run_id
        self.project_id = project_id
        self.workspace_id = workspace_id
        self.book_id = book_id
        self.primary_arc_plan_version_id = primary_arc_plan_version_id
        self.volume_scope_id = volume_scope_id
        self.composition = composition
        self.chapter_application = chapter_application
        self.operator = operator
        self.chapter_worker = chapter_worker
        self.quality = quality_authority
        self.reviewers = tuple(reviewers)
        self.campaign_secret = campaign_secret
        self.mode = mode
        self.book_worker_id = book_worker_id
        self.failure_injector = failure_injector
        self.runtime_jobs = RuntimeJobAuthority(database_url)
        campaign = self.quality.require_campaign(campaign_id, principal=operator)
        self.release_sha = str(campaign["exact_release_sha"])
        self.frozen_pack_bindings = {
            str(role): dict(binding)
            for role, binding in dict(campaign["capability_pack_manifest"]).items()
        }
        self.followup_coordinator = PostgresBookFollowupCoordinator(
            composition.authority,
            query=composition.query,
            principal=operator,
        )
        self._completed_ranges: list[tuple[int, int]] = []

    def run_group(self, chapter_range: tuple[int, int]) -> Mapping[str, Any]:
        self._enforce_campaign_budget()
        expected_index = len(self._completed_ranges)
        if (
            expected_index >= len(self.profile.chapter_group_ranges)
            or chapter_range != self.profile.chapter_group_ranges[expected_index]
        ):
            raise ValueError("ChapterGroup execution differs from frozen 4+4 order")
        group_run_id = self._advance_and_close_group(chapter_range)
        self._inject(f"after_acceptance:{chapter_range[1]}")
        self._drain_followups(chapter_range[1])
        reader_state_id, recap_id = self._group_followup_outputs(chapter_range[1])
        group_effects = self._group_provider_effect_ids(chapter_range)
        if not group_effects:
            raise RuntimeError("Canonical ChapterGroup emitted no Provider effects")
        self._enforce_campaign_budget()
        self._inject(f"after_receipt:{chapter_range[1]}")
        self._completed_ranges.append(chapter_range)
        return {
            "chapter_range": list(chapter_range),
            "accepted_chapters": list(range(chapter_range[0], chapter_range[1] + 1)),
            "provider_effect_ids": list(group_effects),
            "group_run_id": group_run_id,
            "reader_state_asset_version_id": reader_state_id,
            "recap_asset_version_id": recap_id,
        }

    def record_terminal_failure(
        self,
        error: QualityCampaignTerminalError,
    ) -> Mapping[str, Any]:
        """Persist an engineering qualification failure without recasting L1-L3."""

        summary = self._provider_runtime_summary()
        source_ids = tuple(
            dict.fromkeys(
                (
                    *(str(item) for item in summary["model_call_asset_version_ids"]),
                    *(str(item) for item in summary["cost_ledger_asset_version_ids"]),
                )
            )
        )
        if not source_ids:
            raise RuntimeError(
                "terminal campaign failure lacks Provider source AssetVersions"
            )
        campaign = self.quality.require_campaign(
            self.campaign_id,
            principal=self.operator,
        )
        measurements = {
            **error.measurements,
            "provider_dispatch_count": summary["provider_dispatch_count"],
            "real_provider_call_count": summary["real_provider_call_count"],
            "provider_failure_count": summary["provider_failure_count"],
            "provider_retry_count": summary["provider_retry_count"],
            "measured_input_tokens": summary["measured_input_tokens"],
            "measured_output_tokens": summary["measured_output_tokens"],
            "measured_total_tokens": summary["measured_total_tokens"],
            "settled_cost_amount": summary["settled_cost_amount"],
            "currency": summary["currency"],
        }
        return self.quality.record_terminal_failure(
            self.campaign_id,
            expected_version=int(campaign["version"]),
            failure_code=error.failure_code,
            reasons=error.reasons,
            measurements=measurements,
            source_asset_version_ids=source_ids,
            principal=self.operator,
        )

    def final_evidence(self) -> Mapping[str, Any]:
        book = self.composition.authority.require(self.book_run_id)
        if int(book["accepted_through_chapter"]) != 8:
            raise RuntimeError("final Quality evidence requires exactly eight Chapters")
        candidates = self._candidate_pairs()
        if tuple(item.chapter_number for item in candidates) != QUALITY_CHAPTERS:
            raise RuntimeError(
                "baseline comparison lacks an exact Chapter 1-8 sequence"
            )
        observations = load_accepted_quality_observations(
            self.database_url,
            project_id=self.project_id,
            book_id=self.book_id,
            accepted_through_chapter=8,
        )
        if len(observations) != 8 or any(
            not item.get("reader_outcome_asset_version_ids") for item in observations
        ):
            raise RuntimeError(
                "accepted longitudinal evidence requires all eight Reader outcomes"
            )
        longitudinal = build_longitudinal_quality_evidence(observations)
        arc = build_arc_quality_evaluation(
            observations,
            arc_plan_version_id=self.primary_arc_plan_version_id,
        )
        volume = build_volume_slice_quality_evaluation(
            observations,
            arc_evaluations=(arc,),
            volume_scope_id=self.volume_scope_id,
        )
        semantic_evidence_hash = semantic_quality_evidence_identity(
            {
                "comparison_candidates": [
                    {
                        "chapter_number": item.chapter_number,
                        "baseline_text": item.baseline_text,
                        "canonical_text": item.canonical_text,
                    }
                    for item in candidates
                ],
                "longitudinal": longitudinal.to_dict(),
                "arc": arc.to_dict(),
                "volume": volume.to_dict(),
            }
        )
        subjects = self._bind_comparison_subjects(candidates)
        self._inject("after_candidate_materialization")
        provider_runtime = self._provider_runtime_summary()
        self._validate_final_provider_evidence(provider_runtime)
        (
            evidence_asset_ids,
            provider_runtime_asset_id,
            provider_runtime_content_hash,
        ) = self._materialize_and_bind_evidence(
            observations=observations,
            longitudinal=longitudinal.to_dict(),
            arc=arc.to_dict(),
            volume=volume.to_dict(),
            semantic_evidence_hash=semantic_evidence_hash,
            provider_runtime=provider_runtime,
        )
        packs = self._export_blind_packs(subjects)
        self._inject("after_pack_export")
        decision = self.quality.evaluate_campaign(
            self.campaign_id,
            human_collection_closed=False,
            principal=self.operator,
        )
        if (
            decision["campaign_lifecycle"] != "WAITING_HUMAN_EVIDENCE"
            or decision["qualification_status"] != "NOT_PROVEN"
        ):
            raise RuntimeError("zero-human campaign must remain waiting and NOT_PROVEN")
        return {
            "accepted_through_chapter": 8,
            "longitudinal_evidence": longitudinal.to_dict(),
            "arc_evaluations": [arc.to_dict()],
            "volume_evaluation": volume.to_dict(),
            "blind_pack_ids": [packs[item.reviewer_id] for item in self.reviewers],
            "semantic_evidence_hash": semantic_evidence_hash,
            "evidence_asset_version_ids": list(evidence_asset_ids),
            "provider_runtime_evidence": provider_runtime,
            "provider_runtime_evidence_asset_version_id": (provider_runtime_asset_id),
            "provider_runtime_evidence_content_hash": (provider_runtime_content_hash),
            "qualification_decision": decision,
        }

    def _inject(self, stage: str) -> None:
        if self.failure_injector is not None:
            self.failure_injector(stage)

    def _advance_and_close_group(self, chapter_range: tuple[int, int]) -> str:
        start, end = chapter_range
        observed_group_id = ""
        for _ in range(512):
            group = self._group_run(chapter_range)
            if group is not None:
                observed_group_id = str(group["group_run_id"])
                if (
                    int(group["chapter_start"]) != start
                    or int(group["chapter_end"]) != end
                ):
                    raise RuntimeError("Canonical ChapterGroup range drifted")
                if (
                    int(group["accepted_through_chapter"]) == end
                    and str(group["state"]) == "COMPLETED"
                ):
                    return observed_group_id
            book = self.composition.authority.require(self.book_run_id)
            if int(book["accepted_through_chapter"]) > end:
                raise RuntimeError("Book crossed the bounded ChapterGroup stop")
            tick = self._book_worker_tick()
            action = str(tick.get("action") or "")
            if action == "DISPATCH_CHAPTER":
                self._run_chapter(str(tick["operation_id"]))
            elif action == "RECONCILE_CHAPTER":
                # A resumed campaign may already own an admitted/running child.
                # Book reconciliation observes it but does not execute the
                # Chapter worker. Continue the exact frozen child operation;
                # never submit a replacement or mutate its input snapshot.
                self._run_chapter(self._active_chapter_root_operation_id())
        raise RuntimeError(
            f"Canonical Book runtime did not close ChapterGroup {start}-{end}"
        )

    def _book_worker_tick(self) -> dict[str, Any]:
        schedule_book_coordination_jobs(
            self.composition.query,
            self.runtime_jobs,
            limit=1,
            book_run_id=self.book_run_id,
        )
        claim = self.runtime_jobs.claim(
            runtime_group="book",
            worker_id=self.book_worker_id,
            lease_seconds=30,
            job_kinds=("BOOK_COORDINATION_TICK",),
            subject_kind="BOOK_RUN",
            subject_id=self.book_run_id,
        )
        if claim is None:
            raise RuntimeError("Book coordination scheduler produced no claim")
        return execute_book_coordination_claim(
            self.runtime_jobs,
            self.composition,
            claim,
        )

    def _run_chapter(self, root_operation_id: str) -> None:
        scheduler = self.chapter_application.scheduler(principal=self.chapter_worker)
        for _ in range(len(ChapterNode) * 3 + 12):
            tick = scheduler.tick(
                project_id=self.project_id,
                root_operation_id=root_operation_id,
            )
            self._enforce_campaign_budget()
            if tick.saga_status == "SUCCEEDED":
                return
        raise RuntimeError("Chapter Authority did not reach SUCCEEDED")

    def _active_chapter_root_operation_id(self) -> str:
        book = self.composition.authority.require(self.book_run_id)
        request_id = str(book.get("active_chapter_request_id") or "")
        if not request_id:
            raise RuntimeError("Book reconciliation lacks an active Chapter request")
        request = self.composition.authority.require_chapter_request(request_id)
        root_operation_id = str(request.get("chapter_root_operation_id") or "")
        if not root_operation_id:
            raise RuntimeError("active Chapter request lacks its Authority operation")
        return root_operation_id

    def _drain_followups(self, through_chapter: int) -> None:
        for _ in range(96):
            if self._followup_complete(through_chapter):
                return
            candidates = tuple(
                item
                for item in self.followup_coordinator.admission_candidates(limit=32)
                if item.book_run_id == self.book_run_id
                and item.chapter_number <= through_chapter
            )
            if not candidates:
                raise RuntimeError("Reader/Recap follow-up backlog disappeared")
            admitted = self.followup_coordinator.admit(candidates[0])
            self.composition.followup.run_or_recover(
                BookFollowupAdmission(
                    operation_id=admitted.operation_id,
                    project_id=self.project_id,
                    replayed=False,
                )
            )
            self._enforce_campaign_budget()
        raise RuntimeError("Reader/Recap follow-ups did not settle")

    def _followup_complete(self, through_chapter: int) -> bool:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_book_chapter_acceptance AS acceptance
                JOIN authority_reader_outcome_projection AS reader
                  ON reader.book_run_id=acceptance.book_run_id
                 AND reader.chapter_request_id=acceptance.chapter_request_id
                 AND reader.status='SUCCEEDED'
                WHERE acceptance.book_run_id=%s
                  AND acceptance.chapter_number<=%s
                """,
                [self.book_run_id, through_chapter],
            )
            reader_count = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_book_chapter_acceptance AS acceptance
                JOIN authority_longform_recap_projection AS recap
                  ON recap.book_run_id=acceptance.book_run_id
                 AND recap.chapter_request_id=acceptance.chapter_request_id
                 AND recap.status='SUCCEEDED'
                WHERE acceptance.book_run_id=%s
                  AND acceptance.chapter_number=%s
                """,
                [self.book_run_id, through_chapter],
            )
            recap_count = int(uow.cursor.fetchone()[0])
        return reader_count == through_chapter and recap_count == 1

    def _group_run(self, chapter_range: tuple[int, int]) -> dict[str, Any] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT group_run_id, chapter_start, chapter_end,
                       accepted_through_chapter, state
                FROM authority_chapter_group_production
                WHERE book_run_id=%s AND chapter_start=%s AND chapter_end=%s
                ORDER BY created_at
                """,
                [self.book_run_id, chapter_range[0], chapter_range[1]],
            )
            rows = uow.cursor.fetchall()
        if len(rows) > 1:
            raise RuntimeError("bounded campaign materialized duplicate ChapterGroups")
        if not rows:
            return None
        return dict(
            zip(
                (
                    "group_run_id",
                    "chapter_start",
                    "chapter_end",
                    "accepted_through_chapter",
                    "state",
                ),
                rows[0],
                strict=True,
            )
        )

    def _group_followup_outputs(self, chapter_number: int) -> tuple[str, str]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT state.asset_version_id, recap.longform_recap_asset_version
                FROM authority_book_chapter_acceptance AS acceptance
                JOIN authority_book_followup_operation AS reader_link
                  ON reader_link.chapter_request_id=acceptance.chapter_request_id
                 AND reader_link.followup_type='READER_OUTCOME'
                JOIN authority_operation_output_asset AS state
                  ON state.operation_id=reader_link.operation_id
                 AND state.output_key='reader_outcome.state_transition'
                JOIN authority_longform_recap_projection AS recap
                  ON recap.chapter_request_id=acceptance.chapter_request_id
                 AND recap.status='SUCCEEDED'
                WHERE acceptance.book_run_id=%s
                  AND acceptance.chapter_number=%s
                """,
                [self.book_run_id, chapter_number],
            )
            row = uow.cursor.fetchone()
        if row is None or not all(str(item or "") for item in row):
            raise RuntimeError("ChapterGroup Reader/Recap evidence is incomplete")
        return str(row[0]), str(row[1])

    def _group_provider_effect_ids(
        self, chapter_range: tuple[int, int]
    ) -> tuple[str, ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                WITH scoped_operations AS (
                    SELECT operation.operation_id
                    FROM authority_book_chapter_acceptance AS acceptance
                    JOIN authority_book_chapter_request AS request
                      ON request.chapter_request_id=acceptance.chapter_request_id
                    JOIN authority_operation AS operation
                      ON operation.project_id=acceptance.project_id
                     AND (
                          operation.operation_id=request.chapter_root_operation_id
                          OR operation.root_operation_id=
                             request.chapter_root_operation_id
                     )
                    WHERE acceptance.book_run_id=%s
                      AND acceptance.status='COMMITTED'
                      AND acceptance.chapter_number BETWEEN %s AND %s
                    UNION
                    SELECT followup.operation_id
                    FROM authority_book_chapter_acceptance AS acceptance
                    JOIN authority_book_followup_operation AS followup
                      ON followup.chapter_request_id=acceptance.chapter_request_id
                     AND followup.project_id=acceptance.project_id
                    WHERE acceptance.book_run_id=%s
                      AND acceptance.status='COMMITTED'
                      AND acceptance.chapter_number BETWEEN %s AND %s
                )
                SELECT DISTINCT effect.external_effect_id
                FROM scoped_operations
                JOIN authority_external_effect AS effect
                  ON effect.operation_id=scoped_operations.operation_id
                WHERE effect.effect_type='model.invoke'
                ORDER BY effect.external_effect_id
                """,
                [
                    self.book_run_id,
                    chapter_range[0],
                    chapter_range[1],
                    self.book_run_id,
                    chapter_range[0],
                    chapter_range[1],
                ],
            )
            return tuple(str(row[0]) for row in uow.cursor.fetchall())

    @staticmethod
    def _provider_payload(content: Mapping[str, Any]) -> dict[str, Any]:
        nested = content.get("provider_evidence")
        return dict(nested) if isinstance(nested, Mapping) else dict(content)

    @staticmethod
    def _route_role(definition_name: str, stage: str) -> str:
        if definition_name == "story_planning.generate":
            return "planning"
        if stage in {"draft", "revision"}:
            return "generator"
        if stage in {
            "review",
            "rereview",
            "canon_extraction",
            "narrative_semantic_evaluation",
        }:
            return "reviewer"
        if stage.startswith("quality_"):
            return "judge"
        if stage == "reader_outcome":
            return "reader_proxy"
        return ""

    def _provider_runtime_summary(self) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT DISTINCT version.asset_version_id, version.content,
                       operation.operation_id, operation.definition_name
                FROM authority_asset AS asset
                JOIN authority_asset_version AS version
                  ON version.asset_id=asset.asset_id
                JOIN authority_operation_output_asset AS output
                  ON output.asset_version_id=version.asset_version_id
                JOIN authority_operation AS operation
                  ON operation.operation_id=output.operation_id
                WHERE asset.project_id=%s
                  AND asset.asset_type='model_call_log'
                ORDER BY operation.operation_id, version.asset_version_id
                """,
                [self.project_id],
            )
            model_rows = uow.cursor.fetchall()
            uow.cursor.execute(
                """
                SELECT DISTINCT version.asset_version_id
                FROM authority_asset AS asset
                JOIN authority_asset_version AS version
                  ON version.asset_id=asset.asset_id
                WHERE asset.project_id=%s AND asset.asset_type='cost_ledger'
                ORDER BY version.asset_version_id
                """,
                [self.project_id],
            )
            cost_asset_ids = tuple(str(row[0]) for row in uow.cursor.fetchall())
            uow.cursor.execute(
                """
                SELECT effect.external_effect_id, effect.operation_id,
                       effect.capability, effect.status, effect.model_id,
                       COUNT(DISTINCT dispatch.dispatch_id),
                       COUNT(DISTINCT receipt.receipt_id)
                FROM authority_external_effect AS effect
                LEFT JOIN authority_external_effect_dispatch AS dispatch
                  ON dispatch.external_effect_id=effect.external_effect_id
                LEFT JOIN authority_external_receipt AS receipt
                  ON receipt.dispatch_id=dispatch.dispatch_id
                WHERE effect.project_id=%s
                  AND effect.effect_type='model.invoke'
                GROUP BY effect.external_effect_id, effect.operation_id,
                         effect.capability, effect.status, effect.model_id
                ORDER BY effect.external_effect_id
                """,
                [self.project_id],
            )
            effect_rows = uow.cursor.fetchall()
            uow.cursor.execute(
                """
                SELECT reservation_id, operation_id, external_effect_id,
                       provider, status, settled_amount, actual_tokens,
                       budget_breach, evidence
                FROM authority_budget_reservation
                WHERE project_id=%s
                ORDER BY reservation_id
                """,
                [self.project_id],
            )
            budget_rows = uow.cursor.fetchall()
            uow.cursor.execute(
                """
                SELECT snapshot.snapshot_id, snapshot.operation_id,
                       snapshot.attempt_id, snapshot.deployment_id,
                       snapshot.pack_id, snapshot.manifest_hash,
                       snapshot.release_sha, snapshot.snapshot_hash,
                       snapshot.snapshot_payload
                FROM authority_attempt_capability_pack_snapshot AS snapshot
                JOIN authority_operation AS operation
                  ON operation.operation_id=snapshot.operation_id
                WHERE operation.project_id=%s
                ORDER BY snapshot.snapshot_id
                """,
                [self.project_id],
            )
            snapshot_rows = uow.cursor.fetchall()
            uow.cursor.execute(
                """
                SELECT book_run_id
                FROM authority_book_production
                WHERE project_id=%s
                ORDER BY book_run_id
                """,
                [self.project_id],
            )
            book_run_ids = tuple(str(row[0]) for row in uow.cursor.fetchall())
            operation_ids = tuple(str(row[2]) for row in model_rows)
            if operation_ids:
                uow.cursor.execute(
                    """
                    SELECT COUNT(*) FILTER (WHERE attempt_number>1),
                           COUNT(*) FILTER (WHERE status='FAILED')
                    FROM authority_attempt
                    WHERE operation_id=ANY(%s)
                    """,
                    [list(operation_ids)],
                )
                attempt_row = uow.cursor.fetchone()
            else:
                attempt_row = (0, 0)

        effects_by_operation: dict[str, list[str]] = {}
        provider_effects: list[dict[str, Any]] = []
        dispatch_count = 0
        receipt_count = 0
        for row in effect_rows:
            effect_id = str(row[0])
            operation_id = str(row[1])
            effects_by_operation.setdefault(operation_id, []).append(effect_id)
            dispatch_count += int(row[5])
            receipt_count += int(row[6])
            provider_effects.append(
                {
                    "external_effect_id": effect_id,
                    "operation_id": operation_id,
                    "capability": str(row[2]),
                    "status": str(row[3]),
                    "model_id": str(row[4]),
                    "dispatch_count": int(row[5]),
                    "receipt_count": int(row[6]),
                }
            )

        calls: list[dict[str, Any]] = []
        route_mismatches: list[str] = []
        unclassified_calls: list[str] = []
        successful_measurement_missing: list[str] = []
        fixture_calls: list[str] = []
        unique_usage: dict[str, tuple[int, int]] = {}
        for asset_version_id, raw_content, operation_id, definition_name in model_rows:
            content = dict(raw_content)
            provider = self._provider_payload(content)
            production = (
                dict(provider["production_execution"])
                if isinstance(provider.get("production_execution"), Mapping)
                else {}
            )
            process = (
                dict(production["process_evidence"])
                if isinstance(production.get("process_evidence"), Mapping)
                else {}
            )
            execution_request = (
                dict(production["execution_request"])
                if isinstance(production.get("execution_request"), Mapping)
                else {}
            )
            execution_result = (
                dict(production["execution_result"])
                if isinstance(production.get("execution_result"), Mapping)
                else {}
            )
            usage = (
                dict(provider["usage"])
                if isinstance(provider.get("usage"), Mapping)
                else dict(process.get("usage") or {})
            )
            cost = (
                dict(provider["cost"])
                if isinstance(provider.get("cost"), Mapping)
                else dict(process.get("cost") or {})
            )
            stage = str(content.get("stage") or execution_request.get("stage") or "")
            external_effect_id = str(content.get("external_effect_id") or "")
            if not external_effect_id:
                candidates = effects_by_operation.get(str(operation_id), [])
                if len(candidates) == 1:
                    external_effect_id = candidates[0]
            role = self._route_role(str(definition_name), stage)
            expected_route = self.profile.provider_routes[self.mode].get(role, {})
            provider_id = str(provider.get("provider_id") or "")
            model_id = str(provider.get("model_id") or "")
            call_ref = str(asset_version_id)
            if not role:
                unclassified_calls.append(call_ref)
            if role and (
                provider_id != str(expected_route.get("provider") or "")
                or model_id != str(expected_route.get("model") or "")
            ):
                route_mismatches.append(call_ref)
            real_model_call = provider.get("real_model_call") is True
            fixture_protocol_only = provider.get("fixture_protocol_only") is True
            if fixture_protocol_only or not real_model_call:
                fixture_calls.append(call_ref)
            post_provider_failure = content.get("post_provider_failure")
            failure_marker = bool(
                str(content.get("call_status") or "")
                or (
                    isinstance(post_provider_failure, Mapping) and post_provider_failure
                )
            )
            succeeded = not failure_marker and (
                str(execution_result.get("outcome") or "").upper() == "SUCCEEDED"
                or (
                    not str(content.get("call_status") or "")
                    and isinstance(provider.get("result"), Mapping)
                )
            )
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            measured = (
                usage.get("availability") == "AVAILABLE"
                and usage.get("measurement") == "MEASURED"
                and input_tokens + output_tokens > 0
            )
            if succeeded and self.mode == "real" and not measured:
                successful_measurement_missing.append(call_ref)
            usage_key = external_effect_id or f"{operation_id}:{stage}"
            previous = unique_usage.get(usage_key)
            if previous is None or sum(previous) < input_tokens + output_tokens:
                unique_usage[usage_key] = (input_tokens, output_tokens)
            calls.append(
                {
                    "model_call_asset_version_id": call_ref,
                    "operation_id": str(operation_id),
                    "definition_name": str(definition_name),
                    "external_effect_id": external_effect_id,
                    "stage": stage,
                    "route_role": role,
                    "provider_id": provider_id,
                    "model_id": model_id,
                    "real_model_call": real_model_call,
                    "fixture_protocol_only": fixture_protocol_only,
                    "succeeded": succeeded,
                    "usage": {
                        "availability": str(usage.get("availability") or ""),
                        "measurement": str(usage.get("measurement") or ""),
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": int(usage.get("total_tokens") or 0),
                    },
                    "cost": {
                        "availability": str(cost.get("availability") or ""),
                        "measurement": str(cost.get("measurement") or ""),
                        "amount": str(cost.get("amount") or "0"),
                        "currency": str(cost.get("currency") or ""),
                        "estimated": bool(cost.get("estimated", False)),
                        "provider_billed": bool(cost.get("provider_billed", False)),
                        "pricing_ref": str(cost.get("pricing_ref") or ""),
                        "pricing_snapshot_hash": str(
                            cost.get("pricing_snapshot_hash") or ""
                        ),
                    },
                }
            )

        settled_cost = Decimal("0")
        settled_tokens = 0
        unresolved_budget_rows: list[str] = []
        budget_breaches: list[str] = []
        budgets: list[dict[str, Any]] = []
        for row in budget_rows:
            reservation_id = str(row[0])
            status = str(row[4])
            try:
                amount = Decimal(str(row[5]))
            except InvalidOperation as exc:
                raise RuntimeError("Provider budget contains invalid cost") from exc
            if status == "SETTLED":
                settled_cost += amount
                settled_tokens += int(row[6])
            elif status not in {"RELEASED"}:
                unresolved_budget_rows.append(reservation_id)
            if bool(row[7]):
                budget_breaches.append(reservation_id)
            budgets.append(
                {
                    "reservation_id": reservation_id,
                    "operation_id": str(row[1]),
                    "external_effect_id": str(row[2] or ""),
                    "provider": str(row[3]),
                    "status": status,
                    "settled_amount": str(row[5]),
                    "actual_tokens": int(row[6]),
                    "budget_breach": bool(row[7]),
                    "evidence": dict(row[8] or {}),
                }
            )

        expected_deployments = {
            str(binding.get("deployment_id") or "")
            for binding in self.frozen_pack_bindings.values()
        }
        pack_snapshots = [
            {
                "snapshot_id": str(row[0]),
                "operation_id": str(row[1]),
                "attempt_id": str(row[2]),
                "deployment_id": str(row[3]),
                "pack_id": str(row[4]),
                "manifest_hash": str(row[5]),
                "release_sha": str(row[6]),
                "snapshot_hash": str(row[7]),
                "prompt_bundle_hash": str(
                    dict(row[8] or {}).get("prompt_bundle_hash") or ""
                ),
                "prompt_template_hash": str(
                    dict(row[8] or {}).get("prompt_template_hash") or ""
                ),
                "skill_bundle_hash": str(
                    dict(row[8] or {}).get("skill_bundle_hash") or ""
                ),
                "skill_content_hash": str(
                    dict(row[8] or {}).get("skill_content_hash") or ""
                ),
                "route_policy_hash": str(
                    dict(row[8] or {}).get("route_policy_hash") or ""
                ),
                "context_policy_hash": str(
                    dict(row[8] or {}).get("context_policy_hash") or ""
                ),
                "evaluation_policy_hash": str(
                    dict(row[8] or {}).get("evaluation_policy_hash") or ""
                ),
            }
            for row in snapshot_rows
        ]
        pack_snapshot_drift = [
            item["snapshot_id"]
            for item in pack_snapshots
            if item["deployment_id"] not in expected_deployments
            or item["release_sha"] != self.release_sha
        ]
        pack_snapshot_semantic_hash_missing = [
            item["snapshot_id"]
            for item in pack_snapshots
            if any(
                not item[field]
                for field in (
                    "manifest_hash",
                    "prompt_bundle_hash",
                    "skill_bundle_hash",
                    "route_policy_hash",
                    "context_policy_hash",
                    "evaluation_policy_hash",
                )
            )
        ]
        snapshot_operation_ids = {item["operation_id"] for item in pack_snapshots}
        missing_snapshot_operations = sorted(
            {
                item["operation_id"]
                for item in calls
                if item["operation_id"] not in snapshot_operation_ids
            }
        )
        measured_input_tokens = sum(item[0] for item in unique_usage.values())
        measured_output_tokens = sum(item[1] for item in unique_usage.values())
        provider_failures = sum(1 for item in calls if not bool(item["succeeded"]))
        successful_effect_missing_receipts = sorted(
            item["external_effect_id"]
            for item in provider_effects
            if item["status"] == "SUCCEEDED" and int(item["receipt_count"]) <= 0
        )
        return {
            "schema_version": "novel-forge.provider-runtime-evidence.v1",
            "mode": self.mode,
            "project_scope_policy": "DEDICATED_CAMPAIGN_PROJECT",
            "book_run_ids": list(book_run_ids),
            "model_call_count": len(calls),
            "provider_dispatch_count": dispatch_count,
            "provider_receipt_count": receipt_count,
            "real_provider_call_count": sum(
                1 for item in calls if item["real_model_call"] is True
            ),
            "provider_failure_count": provider_failures,
            "provider_retry_count": int(attempt_row[0]),
            "failed_attempt_count": int(attempt_row[1]),
            "measured_input_tokens": measured_input_tokens,
            "measured_output_tokens": measured_output_tokens,
            "measured_total_tokens": settled_tokens,
            "settled_cost_amount": format(settled_cost, "f"),
            "currency": "USD",
            "route_mismatch_asset_version_ids": sorted(route_mismatches),
            "unclassified_model_call_asset_version_ids": sorted(unclassified_calls),
            "fixture_call_asset_version_ids": sorted(fixture_calls),
            "successful_measurement_missing_asset_version_ids": sorted(
                successful_measurement_missing
            ),
            "unresolved_budget_reservation_ids": sorted(unresolved_budget_rows),
            "budget_breach_reservation_ids": sorted(budget_breaches),
            "successful_effect_missing_receipt_ids": (
                successful_effect_missing_receipts
            ),
            "pack_snapshot_drift_ids": sorted(pack_snapshot_drift),
            "pack_snapshot_semantic_hash_missing_ids": sorted(
                pack_snapshot_semantic_hash_missing
            ),
            "missing_pack_snapshot_operation_ids": missing_snapshot_operations,
            "model_calls": calls,
            "provider_effects": provider_effects,
            "budget_reservations": budgets,
            "capability_pack_snapshots": pack_snapshots,
            "model_call_asset_version_ids": [str(row[0]) for row in model_rows],
            "cost_ledger_asset_version_ids": list(cost_asset_ids),
        }

    def _enforce_campaign_budget(self) -> None:
        summary = self._provider_runtime_summary()
        budget = self.profile.to_dict()["budget_policy"]
        failures: list[str] = []
        for field, limit_field in (
            ("provider_dispatch_count", "provider_call_limit"),
            ("provider_retry_count", "retry_limit"),
            ("measured_input_tokens", "input_token_limit"),
            ("measured_output_tokens", "output_token_limit"),
            ("measured_total_tokens", "token_limit"),
        ):
            if int(summary[field]) > int(budget[limit_field]):
                failures.append(f"{field}>{limit_field}")
        if Decimal(str(summary["settled_cost_amount"])) > Decimal(
            str(budget["cost_limit_usd"])
        ):
            failures.append("settled_cost_amount>cost_limit_usd")
        if summary["budget_breach_reservation_ids"]:
            failures.append("budget_breach")
        if summary["pack_snapshot_drift_ids"]:
            failures.append("capability_pack_snapshot_drift")
        if failures:
            measurements = {
                field: summary[field]
                for field in (
                    "provider_dispatch_count",
                    "provider_retry_count",
                    "measured_input_tokens",
                    "measured_output_tokens",
                    "measured_total_tokens",
                    "settled_cost_amount",
                )
            }
            measurements["budget_policy"] = {
                key: budget[key]
                for key in (
                    "provider_call_limit",
                    "retry_limit",
                    "input_token_limit",
                    "output_token_limit",
                    "token_limit",
                    "cost_limit_usd",
                )
            }
            raise QualityCampaignTerminalError(
                "CAMPAIGN_BUDGET_OR_LINEAGE_BREACH",
                "bounded Quality campaign budget/lineage failed closed: "
                + ", ".join(failures),
                reasons=tuple(failures),
                measurements=measurements,
            )

    def _validate_final_provider_evidence(self, summary: Mapping[str, Any]) -> None:
        self._enforce_campaign_budget()
        failures: list[str] = []
        if list(summary["book_run_ids"]) != [self.book_run_id]:
            failures.append("campaign project is not dedicated to one Book run")
        if int(summary["model_call_count"]) <= 0:
            failures.append("model call evidence is missing")
        if summary["unresolved_budget_reservation_ids"]:
            failures.append("provider budget settlement is incomplete")
        if summary["route_mismatch_asset_version_ids"]:
            failures.append("Provider/model route evidence drifted")
        if summary["unclassified_model_call_asset_version_ids"]:
            failures.append("model calls are outside the frozen role map")
        if summary["successful_effect_missing_receipt_ids"]:
            failures.append("successful Provider effects lack receipts")
        if self.mode == "real":
            if summary["fixture_call_asset_version_ids"]:
                failures.append("fixture Provider evidence contaminated real campaign")
            if summary["successful_measurement_missing_asset_version_ids"]:
                failures.append("successful real calls lack measured usage")
            if summary["missing_pack_snapshot_operation_ids"]:
                failures.append("real Provider operations lack Pack snapshots")
            if summary["pack_snapshot_semantic_hash_missing_ids"]:
                failures.append("Pack snapshots lack Prompt/Skill/policy hashes")
            if int(summary["real_provider_call_count"]) <= 0:
                failures.append("no attributable real Provider call")
        if failures:
            raise QualityCampaignTerminalError(
                "CAMPAIGN_PROVIDER_EVIDENCE_INCOMPLETE",
                "final Provider runtime evidence is incomplete: " + "; ".join(failures),
                reasons=tuple(failures),
                measurements={
                    "provider_dispatch_count": summary["provider_dispatch_count"],
                    "real_provider_call_count": summary["real_provider_call_count"],
                    "provider_failure_count": summary["provider_failure_count"],
                    "provider_retry_count": summary["provider_retry_count"],
                    "measured_total_tokens": summary["measured_total_tokens"],
                    "settled_cost_amount": summary["settled_cost_amount"],
                },
            )

    def _candidate_pairs(self) -> tuple[_CandidatePair, ...]:
        rows: list[_CandidatePair] = []
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT acceptance.chapter_number,
                       acceptance.chapter_outcome_asset_version_id,
                       outcome.content,
                       request.chapter_plan_version,
                       realization.content_asset_version_id,
                       baseline.asset_version_id, baseline.content_hash,
                       baseline_version.content,
                       canonical.asset_version_id, canonical.content_hash,
                       canonical_version.content
                FROM authority_book_chapter_acceptance AS acceptance
                JOIN authority_asset_version AS outcome
                  ON outcome.asset_version_id=
                     acceptance.chapter_outcome_asset_version_id
                JOIN authority_book_chapter_request AS request
                  ON request.chapter_request_id=acceptance.chapter_request_id
                JOIN authority_narrative_realization AS realization
                  ON realization.realization_id=request.narrative_realization_id
                JOIN authority_operation AS baseline_operation
                  ON baseline_operation.root_operation_id=
                     request.chapter_root_operation_id
                 AND baseline_operation.project_id=acceptance.project_id
                JOIN authority_operation_output_asset AS baseline
                  ON baseline.operation_id=baseline_operation.operation_id
                 AND baseline.output_key='chapter.draft'
                JOIN authority_asset_version AS baseline_version
                  ON baseline_version.asset_version_id=baseline.asset_version_id
                JOIN authority_operation_output_asset AS canonical
                  ON canonical.asset_version_id=
                     outcome.content->>'accepted_draft_asset_version_id'
                JOIN authority_asset_version AS canonical_version
                  ON canonical_version.asset_version_id=canonical.asset_version_id
                WHERE acceptance.book_run_id=%s
                  AND acceptance.status='COMMITTED'
                ORDER BY acceptance.chapter_number
                """,
                [self.book_run_id],
            )
            for row in uow.cursor.fetchall():
                chapter = int(row[0])
                baseline_content = dict(row[7] or {})
                canonical_content = dict(row[10] or {})
                rows.append(
                    _CandidatePair(
                        chapter_number=chapter,
                        subject_id=f"quality-subject:{self.campaign_id}:chapter:{chapter}",
                        accepted_outcome_asset_version_id=str(row[1]),
                        chapter_plan_asset_version_id=str(row[3]),
                        narrative_realization_asset_version_id=str(row[4]),
                        baseline_asset_version_id=str(row[5]),
                        baseline_content_hash=str(row[6]),
                        baseline_text=str(baseline_content.get("text") or ""),
                        canonical_asset_version_id=str(row[8]),
                        canonical_content_hash=str(row[9]),
                        canonical_text=str(canonical_content.get("text") or ""),
                    )
                )
        if any(
            not item.baseline_text
            or not item.canonical_text
            or item.baseline_asset_version_id == item.canonical_asset_version_id
            for item in rows
        ):
            raise RuntimeError("first-draft baseline is not comparable to acceptance")
        return tuple(rows)

    def _bind_comparison_subjects(
        self, candidates: Sequence[_CandidatePair]
    ) -> tuple[BlindComparisonSubject, ...]:
        blind: list[BlindComparisonSubject] = []
        for item in candidates:
            self.quality.bind_subject(
                QualitySubjectBindingCommand(
                    campaign_id=self.campaign_id,
                    subject_id=item.subject_id,
                    scope_type="CHAPTER",
                    scope_key=f"chapter:{item.chapter_number}",
                    chapter_start=item.chapter_number,
                    chapter_end=item.chapter_number,
                    arc_plan_version_ids=(self.primary_arc_plan_version_id,),
                    canonical_asset_version_id=item.canonical_asset_version_id,
                    canonical_content_hash=item.canonical_content_hash,
                    baseline_asset_version_id=item.baseline_asset_version_id,
                    baseline_content_hash=item.baseline_content_hash,
                    chapter_plan_asset_version_id=item.chapter_plan_asset_version_id,
                    narrative_realization_asset_version_id=(
                        item.narrative_realization_asset_version_id
                    ),
                ),
                principal=self.operator,
            )
            blind.append(
                BlindComparisonSubject(
                    subject_id=item.subject_id,
                    scope_type=BlindScope.CHAPTER,
                    chapter_start=item.chapter_number,
                    chapter_end=item.chapter_number,
                    canonical_asset_version_id=item.canonical_asset_version_id,
                    baseline_asset_version_id=item.baseline_asset_version_id,
                    canonical_text=item.canonical_text,
                    baseline_text=item.baseline_text,
                    arc_plan_version_ids=(self.primary_arc_plan_version_id,),
                )
            )
        canonical_sequence = "\n\n".join(
            f"Chapter {item.chapter_number}\n{item.canonical_text}"
            for item in candidates
        )
        baseline_sequence = "\n\n".join(
            f"Chapter {item.chapter_number}\n{item.baseline_text}"
            for item in candidates
        )
        source_ids = tuple(
            item.canonical_asset_version_id for item in candidates
        ) + tuple(item.baseline_asset_version_id for item in candidates)
        canonical_arc = self.quality.materialize_artifact(
            QualityArtifactMaterializationCommand(
                campaign_id=self.campaign_id,
                artifact_id="arc:primary:canonical-sequence",
                artifact_kind="COMPARISON_CANDIDATE",
                scope_type="ARC",
                chapter_start=1,
                chapter_end=8,
                content={
                    "candidate_role": "CANONICAL_ACCEPTED_SEQUENCE",
                    "text": canonical_sequence,
                },
                source_asset_version_ids=tuple(
                    item.canonical_asset_version_id for item in candidates
                ),
            ),
            principal=self.operator,
        )
        baseline_arc = self.quality.materialize_artifact(
            QualityArtifactMaterializationCommand(
                campaign_id=self.campaign_id,
                artifact_id="arc:primary:baseline-sequence",
                artifact_kind="COMPARISON_CANDIDATE",
                scope_type="ARC",
                chapter_start=1,
                chapter_end=8,
                content={
                    "candidate_role": "FIRST_DRAFT_SEQUENCE",
                    "text": baseline_sequence,
                },
                source_asset_version_ids=tuple(
                    item.baseline_asset_version_id for item in candidates
                ),
            ),
            principal=self.operator,
        )
        arc_subject_id = f"quality-subject:{self.campaign_id}:arc:primary"
        self.quality.bind_subject(
            QualitySubjectBindingCommand(
                campaign_id=self.campaign_id,
                subject_id=arc_subject_id,
                scope_type="ARC",
                scope_key="arc:primary:chapters:1-8",
                chapter_start=1,
                chapter_end=8,
                arc_plan_version_ids=(self.primary_arc_plan_version_id,),
                canonical_asset_version_id=canonical_arc["asset_version_id"],
                canonical_content_hash=canonical_arc["content_hash"],
                baseline_asset_version_id=baseline_arc["asset_version_id"],
                baseline_content_hash=baseline_arc["content_hash"],
            ),
            principal=self.operator,
        )
        blind.append(
            BlindComparisonSubject(
                subject_id=arc_subject_id,
                scope_type=BlindScope.ARC,
                chapter_start=1,
                chapter_end=8,
                canonical_asset_version_id=canonical_arc["asset_version_id"],
                baseline_asset_version_id=baseline_arc["asset_version_id"],
                canonical_text=canonical_sequence,
                baseline_text=baseline_sequence,
                arc_plan_version_ids=(self.primary_arc_plan_version_id,),
            )
        )
        if len(set(source_ids)) != 16:
            raise RuntimeError("Arc comparison corpus lost candidate lineage")
        return tuple(blind)

    def _materialize_and_bind_evidence(
        self,
        *,
        observations: Sequence[Mapping[str, Any]],
        longitudinal: dict[str, Any],
        arc: dict[str, Any],
        volume: dict[str, Any],
        semantic_evidence_hash: str,
        provider_runtime: Mapping[str, Any],
    ) -> tuple[tuple[str, ...], str, str]:
        accepted_ids = tuple(
            str(item["accepted_asset_version_id"]) for item in observations
        )
        reader_ids = tuple(
            str(version_id)
            for item in observations
            for version_id in item.get("reader_outcome_asset_version_ids") or ()
        )
        provider_source_ids = tuple(
            dict.fromkeys(
                (
                    *(
                        str(item)
                        for item in provider_runtime["model_call_asset_version_ids"]
                    ),
                    *(
                        str(item)
                        for item in provider_runtime["cost_ledger_asset_version_ids"]
                    ),
                )
            )
        )
        if not provider_source_ids:
            raise RuntimeError("Provider runtime evidence has no source AssetVersions")
        provider_artifact = self.quality.materialize_artifact(
            QualityArtifactMaterializationCommand(
                campaign_id=self.campaign_id,
                artifact_id="evidence:provider-runtime",
                artifact_kind="EVIDENCE_REPORT",
                scope_type="CAMPAIGN",
                chapter_start=1,
                chapter_end=8,
                content={
                    "report_type": "BOUNDED_PROVIDER_RUNTIME_EVIDENCE",
                    "report": dict(provider_runtime),
                },
                source_asset_version_ids=provider_source_ids,
            ),
            principal=self.operator,
        )
        provider_artifact_id = str(provider_artifact["asset_version_id"])
        reports = (
            (
                "hard-correctness",
                "CAMPAIGN",
                EvidenceLayer.L1_HARD_CORRECTNESS,
                "ACCEPTED_HARD_CORRECTNESS_SEQUENCE",
                EvidenceStatus.PASS,
                EvidenceSeverity.INFO,
                {
                    "accepted_chapter_count": 8,
                    "severe_correctness_failures": [],
                    "narrative_realization_coverage": [
                        item.get("realization_coverage") for item in observations
                    ],
                },
                (*accepted_ids, provider_artifact_id),
            ),
            (
                "automated-editorial",
                "CAMPAIGN",
                EvidenceLayer.L2_EDITORIAL_QUALITY,
                "DEPENDENT_AUTOMATED_EDITORIAL_SEQUENCE",
                EvidenceStatus.PASS_WITH_LIMITATIONS,
                EvidenceSeverity.WARNING,
                {
                    "judge_independence": "DEPENDENT_SAME_MODEL",
                    "human_preference_required": True,
                    "chapter_quality_gates": [
                        item.get("quality_gate") for item in observations
                    ],
                },
                (*accepted_ids, provider_artifact_id),
            ),
            (
                "longitudinal",
                "VOLUME_SLICE",
                EvidenceLayer.L3_READER_LONGITUDINAL,
                "ACCEPTED_LONGITUDINAL_QUALITY",
                EvidenceStatus.PASS_WITH_LIMITATIONS,
                EvidenceSeverity.WARNING,
                {"longitudinal": longitudinal, "arc": arc, "volume": volume},
                tuple(
                    dict.fromkeys((*accepted_ids, *reader_ids, provider_artifact_id))
                ),
            ),
        )
        materialized: list[str] = []
        for (
            label,
            scope,
            layer,
            evidence_type,
            status,
            severity,
            report,
            sources,
        ) in reports:
            artifact = self.quality.materialize_artifact(
                QualityArtifactMaterializationCommand(
                    campaign_id=self.campaign_id,
                    artifact_id=f"evidence:{label}",
                    artifact_kind="EVIDENCE_REPORT",
                    scope_type=scope,
                    chapter_start=1,
                    chapter_end=8,
                    content={
                        "report_type": evidence_type,
                        "semantic_evidence_hash": semantic_evidence_hash,
                        "report": report,
                    },
                    source_asset_version_ids=tuple(sources),
                ),
                principal=self.operator,
            )
            self.quality.bind_evidence(
                QualityEvidenceBindingCommand(
                    campaign_id=self.campaign_id,
                    evidence_id=f"quality-evidence:{self.campaign_id}:{label}",
                    subject_id="",
                    evidence_layer=layer,
                    evidence_type=evidence_type,
                    evidence_asset_version_id=artifact["asset_version_id"],
                    evidence_content_hash=artifact["content_hash"],
                    status=status,
                    severity=severity,
                    source_asset_version_ids=tuple(sources),
                    evaluator_lineage={
                        "profile": self.profile.to_dict()["profiles"],
                        "human_simulation_used": False,
                    },
                    provider_lineage={
                        "mode": self.mode,
                        "campaign_profile_digest": self.profile.digest,
                        "routes": self.profile.provider_routes[self.mode],
                        "independence": "DEPENDENT_SAME_MODEL",
                    },
                ),
                principal=self.operator,
            )
            materialized.append(artifact["asset_version_id"])
        return (
            tuple(materialized),
            provider_artifact_id,
            str(provider_artifact["content_hash"]),
        )

    def _export_blind_packs(
        self, subjects: Iterable[BlindComparisonSubject]
    ) -> dict[str, str]:
        protocol = self.profile.to_dict()["profiles"]
        task = self.quality.reader_calibration.create_preference_task(
            project_id=self.project_id,
            workspace_id=self.workspace_id,
            book_id=self.book_id,
            reader_segment="bounded-quality-human-reviewers",
            evidence_level="HUMAN_VERIFIED",
            idempotency_key=f"{self.campaign_id}:human-blind-task",
            principal=self.operator,
            campaign_id=self.campaign_id,
            protocol_version=protocol["protocol_version"],
            evaluation_profile_version=protocol["evaluation_profile_version"],
            required_evaluator_count=2,
            evaluator_identity_classes=tuple(
                item.identity_class.value for item in self.reviewers
            ),
            scope_manifest={
                "chapter_pairs_per_evaluator": 8,
                "arc_pairs_per_evaluator": 1,
                "chapter_sequence": list(QUALITY_CHAPTERS),
                "ordering": "DETERMINISTIC_BALANCED_COMPLEMENTARY",
                "llm_human_simulation_allowed": False,
            },
        )
        bundle = export_blind_evaluation_packs(
            campaign_token=self.campaign_id,
            campaign_version=self.profile.profile_version,
            protocol_version=protocol["protocol_version"],
            evaluation_version=protocol["evaluation_profile_version"],
            campaign_secret=self.campaign_secret,
            evaluators=(
                BlindEvaluator(item.reviewer_id, item.identity_class)
                for item in self.reviewers
            ),
            subjects=subjects,
        )
        registered = self.quality.reader_calibration.register_blind_packs(
            task_id=str(task["task_id"]),
            bundle=bundle,
            principal=self.operator,
        )
        if len(registered) != 2 or any(
            int(item["pair_count"]) != 9 for item in registered.values()
        ):
            raise RuntimeError("blind export did not create two nine-pair packs")
        return {
            reviewer_id: str(item["pack_id"])
            for reviewer_id, item in registered.items()
        }


__all__ = [
    "HumanReviewerTarget",
    "PostgresBoundedQualityCampaignRuntime",
]
