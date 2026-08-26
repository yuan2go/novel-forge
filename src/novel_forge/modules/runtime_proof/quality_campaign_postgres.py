"""PostgreSQL adapter for the exact two-by-four Quality campaign.

The adapter coordinates existing Authorities. It does not own Chapter truth,
Provider effects, Reader state, Canon, plans, or human decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
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
        self.book_worker_id = book_worker_id
        self.failure_injector = failure_injector
        self.runtime_jobs = RuntimeJobAuthority(database_url)
        self.followup_coordinator = PostgresBookFollowupCoordinator(
            composition.authority,
            query=composition.query,
            principal=operator,
        )
        self._completed_ranges: list[tuple[int, int]] = []

    def run_group(self, chapter_range: tuple[int, int]) -> Mapping[str, Any]:
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
        evidence_asset_ids = self._materialize_and_bind_evidence(
            observations=observations,
            longitudinal=longitudinal.to_dict(),
            arc=arc.to_dict(),
            volume=volume.to_dict(),
            semantic_evidence_hash=semantic_evidence_hash,
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
            if str(tick.get("action") or "") == "DISPATCH_CHAPTER":
                self._run_chapter(str(tick["operation_id"]))
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
            if tick.saga_status == "SUCCEEDED":
                return
        raise RuntimeError("Chapter Authority did not reach SUCCEEDED")

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
                SELECT DISTINCT effect.external_effect_id
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
                JOIN authority_external_effect AS effect
                  ON effect.operation_id=operation.operation_id
                WHERE acceptance.book_run_id=%s
                  AND acceptance.status='COMMITTED'
                  AND acceptance.chapter_number BETWEEN %s AND %s
                ORDER BY effect.external_effect_id
                """,
                [self.book_run_id, chapter_range[0], chapter_range[1]],
            )
            return tuple(str(row[0]) for row in uow.cursor.fetchall())

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
    ) -> tuple[str, ...]:
        accepted_ids = tuple(
            str(item["accepted_asset_version_id"]) for item in observations
        )
        reader_ids = tuple(
            str(version_id)
            for item in observations
            for version_id in item.get("reader_outcome_asset_version_ids") or ()
        )
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
                accepted_ids,
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
                accepted_ids,
            ),
            (
                "longitudinal",
                "VOLUME_SLICE",
                EvidenceLayer.L3_READER_LONGITUDINAL,
                "ACCEPTED_LONGITUDINAL_QUALITY",
                EvidenceStatus.PASS_WITH_LIMITATIONS,
                EvidenceSeverity.WARNING,
                {"longitudinal": longitudinal, "arc": arc, "volume": volume},
                tuple(dict.fromkeys((*accepted_ids, *reader_ids))),
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
                        "routes": self.profile.provider_routes["scripted"],
                        "independence": "DEPENDENT_SAME_MODEL",
                    },
                ),
                principal=self.operator,
            )
            materialized.append(artifact["asset_version_id"])
        return tuple(materialized)

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
