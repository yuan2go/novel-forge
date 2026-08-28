from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

import pytest
from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_authority import (
    BookProductionInputResolver,
    OpenBookProductionRequest,
    PostgresBookOpeningApplication,
)
from novel_forge.modules.book_authority import recovery as recovery_module
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    NarrativeSearchRequest,
    PostgresNarrativeSearchApplication,
    StoryPlanningGenerationApplication,
    canonical_hash,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.workers.book_authority import execute_book_opening_claim
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
)
from tests.integration.book_opening_recovery_postgres_support import (
    LegacyBookOpeningOrphan,
    SimulatedBookOpeningProcessLoss,
    create_legacy_book_opening_orphan,
)
from tests.integration.test_core_functional_loops_postgres import (
    _ExternalEffectPepFixturePlanningBinder,
    _activate_planning_pack,
    _principal,
    _seed_inputs,
)
from tests.integration.capability_pack_postgres_support import (
    CapabilityPackPostgresHarness,
)


RELEASE_A_BUILD = "core-functional-loop-fixture"
RELEASE_A_SHA = "e" * 40
RELEASE_B_BUILD = "book-opening-review-blockers-release-b"
RELEASE_B_SHA = "b" * 40


def _converge_loss(orphan: LegacyBookOpeningOrphan, *, suffix: str) -> None:
    key = f"review-blocker-loss:{orphan.opening_run_id}:{suffix}"
    assessment = orphan.opening.recovery.assess_execution_loss(
        orphan.opening_run_id,
        idempotency_key=key,
        principal=orphan.principal,
    )
    receipt = orphan.opening.recovery.converge_execution_loss(
        assessment.recovery_assessment_id,
        idempotency_key=key,
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    assert receipt.result["opening_lifecycle"] == "FAILED"
    assert receipt.result["execution_lifecycle"] == "LOST"


def _release_b(
    opening: PostgresBookOpeningApplication,
) -> PostgresBookOpeningApplication:
    return PostgresBookOpeningApplication(
        DATABASE_URL,
        narrative_search=opening.narrative_search,
        input_resolver=opening.input_resolver,
        application_build_id=RELEASE_B_BUILD,
        commit_sha=RELEASE_B_SHA,
    )


def _successor_counts(orphan: LegacyBookOpeningOrphan) -> tuple[int, ...]:
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT
              (SELECT COUNT(*)
               FROM authority_book_opening_recovery_intent
               WHERE opening_run_id=%s),
              (SELECT COUNT(*)
               FROM authority_book_opening_execution
               WHERE opening_run_id=%s),
              (SELECT COUNT(*)
               FROM authority_runtime_job
               WHERE subject_kind='BOOK_OPENING_RUN' AND subject_id=%s),
              (SELECT COUNT(*)
               FROM authority_narrative_evaluation_execution
               WHERE project_id=%s AND candidate_asset_version_id=%s)
            """,
            [
                orphan.opening_run_id,
                orphan.opening_run_id,
                orphan.opening_run_id,
                orphan.project_id,
                orphan.evaluation_command.candidate_asset_version_id,
            ],
        )
        row = uow.cursor.fetchone()
    assert row is not None
    return tuple(int(value) for value in row)


def test_rolling_release_can_claim_stable_admission_but_not_reuse_old_assessment() -> (
    None
):
    """Release identity fences RecoveryAssessment, not an unclaimed execution."""

    ensure_migrated()
    admitted = create_legacy_book_opening_orphan()
    _converge_loss(admitted, suffix="admit-successor")
    recovery_assessment = admitted.opening.recovery.assess_recovery(
        admitted.opening_run_id,
        idempotency_key=f"review-blocker-recover:{admitted.opening_run_id}:release-a",
        principal=admitted.principal,
    )
    receipt = admitted.opening.recovery.recover(
        recovery_assessment.recovery_assessment_id,
        idempotency_key=f"review-blocker-admit:{admitted.opening_run_id}:release-a",
        reason="release A admits a stable successor execution",
        principal=admitted.principal,
        expected_opening_run_id=admitted.opening_run_id,
    )
    assert receipt.result["execution_generation"] == 2

    release_b = _release_b(admitted.opening)
    assert (
        release_b.recovery._authority_digest()
        == admitted.opening.recovery._authority_digest()
    )
    assert (
        release_b.recovery._application_release_digest()
        != admitted.opening.recovery._application_release_digest()
    )
    claim = release_b.claim_next_execution(
        worker_id="rolling-release-b-worker",
        lease_seconds=30,
        project_id=admitted.project_id,
    )
    assert claim is not None
    assert claim.runtime_job_id == receipt.result["runtime_job_id"]
    assert claim.input_snapshot["execution_generation"] == 2

    stale = create_legacy_book_opening_orphan()
    _converge_loss(stale, suffix="release-bound-assessment")
    assessment_from_a = stale.opening.recovery.assess_recovery(
        stale.opening_run_id,
        idempotency_key=f"review-blocker-assess:{stale.opening_run_id}:release-a",
        principal=stale.principal,
    )
    before = _successor_counts(stale)
    with pytest.raises(KernelError) as drift:
        _release_b(stale.opening).recovery.recover(
            assessment_from_a.recovery_assessment_id,
            idempotency_key=f"review-blocker-recover:{stale.opening_run_id}:release-b",
            reason="release B must reassess immutable evidence",
            principal=stale.principal,
            expected_opening_run_id=stale.opening_run_id,
        )
    assert drift.value.code == "BOOK_OPENING_RECOVERY_REASSESSMENT_REQUIRED"
    assert _successor_counts(stale) == before == (0, 1, 1, 1)


def test_terminal_semantic_replacement_generation_cap_fails_before_admission() -> None:
    """The bounded policy is checked before Intent/job/generation mutation."""

    ensure_migrated()
    with patch.object(
        recovery_module,
        "BOOK_OPENING_MAX_SEMANTIC_EVALUATION_GENERATIONS",
        1,
    ):
        orphan = create_legacy_book_opening_orphan()
        _converge_loss(orphan, suffix="generation-cap")
        assessment = orphan.opening.recovery.assess_recovery(
            orphan.opening_run_id,
            idempotency_key=f"review-blocker-cap-assess:{orphan.opening_run_id}",
            principal=orphan.principal,
        )
        assert assessment.snapshot["semantic_evaluation"]["generation"] == 1
        before = _successor_counts(orphan)

        with pytest.raises(KernelError) as exhausted:
            orphan.opening.recovery.recover(
                assessment.recovery_assessment_id,
                idempotency_key=f"review-blocker-cap-recover:{orphan.opening_run_id}",
                reason="bounded semantic replacement policy",
                principal=orphan.principal,
                expected_opening_run_id=orphan.opening_run_id,
            )
        assert (
            exhausted.value.code == "BOOK_OPENING_SEMANTIC_REPLACEMENT_POLICY_EXHAUSTED"
        )
        assert _successor_counts(orphan) == before == (0, 1, 1, 1)
        run = orphan.opening.require(orphan.opening_run_id)
        assert (run["lifecycle"], run["current_execution_generation"]) == (
            "FAILED",
            1,
        )


def test_recovery_policy_drift_requires_a_fresh_immutable_assessment() -> None:
    """A policy rollout cannot reuse a snapshot authorized under older rules."""

    ensure_migrated()
    orphan = create_legacy_book_opening_orphan()
    _converge_loss(orphan, suffix="policy-drift")
    assessment = orphan.opening.recovery.assess_recovery(
        orphan.opening_run_id,
        idempotency_key=f"review-blocker-policy-assess:{orphan.opening_run_id}",
        principal=orphan.principal,
    )
    before = _successor_counts(orphan)

    with patch.object(
        recovery_module,
        "BOOK_OPENING_MAX_SEMANTIC_EVALUATION_GENERATIONS",
        4,
    ):
        with pytest.raises(KernelError) as drift:
            orphan.opening.recovery.recover(
                assessment.recovery_assessment_id,
                idempotency_key=(
                    f"review-blocker-policy-recover:{orphan.opening_run_id}"
                ),
                reason="policy drift requires reassessment",
                principal=orphan.principal,
                expected_opening_run_id=orphan.opening_run_id,
            )
    assert drift.value.code == "BOOK_OPENING_RECOVERY_REASSESSMENT_REQUIRED"
    assert _successor_counts(orphan) == before == (0, 1, 1, 1)


def test_recovery_replaces_only_failed_branch_after_successful_search_prefix() -> None:
    """A completed sibling branch is immutable and outside replacement scope."""

    ensure_migrated()
    orphan = create_legacy_book_opening_orphan(
        evaluator_execution_class="SCRIPTED_FIXTURE",
        successful_search_branches_before_crash=1,
    )
    _converge_loss(orphan, suffix="branch-two-only")
    assessment = orphan.opening.recovery.assess_recovery(
        orphan.opening_run_id,
        idempotency_key=f"review-blocker-branch-assess:{orphan.opening_run_id}",
        principal=orphan.principal,
    )
    semantic = assessment.snapshot["semantic_evaluation"]
    assert semantic["operation_id"] == orphan.evaluation_operation_id
    assert semantic["candidate_asset_version_id"] == (
        orphan.evaluation_command.candidate_asset_version_id
    )
    assert semantic["operation_status"] == "CANCELLED"

    receipt = orphan.opening.recovery.recover(
        assessment.recovery_assessment_id,
        idempotency_key=f"review-blocker-branch-recover:{orphan.opening_run_id}",
        reason="only the interrupted second search branch may be replaced",
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    replacement_operation_id = str(
        receipt.result["replacement_evaluation_operation_id"]
    )
    assert replacement_operation_id
    search_id = str(
        orphan.planning.require_generation(
            orphan.evaluation_command.generation_operation_id
        )["narrative_search_id"]
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT generation.narrative_search_branch_key,
                   evaluation.generation,evaluation.operation_id,
                   COALESCE(evaluation.predecessor_operation_id,''),
                   operation.status
            FROM authority_story_planning_generation AS generation
            JOIN authority_narrative_evaluation_execution AS evaluation
              ON evaluation.project_id=generation.project_id
             AND evaluation.candidate_asset_version_id=
                 generation.candidate_asset_version_id
            JOIN authority_operation AS operation
              ON operation.operation_id=evaluation.operation_id
            WHERE generation.project_id=%s
              AND generation.narrative_search_id=%s
            ORDER BY generation.narrative_search_branch_key,
                     evaluation.generation
            """,
            [orphan.project_id, search_id],
        )
        lineage = [tuple(str(value) for value in row) for row in uow.cursor.fetchall()]
        uow.cursor.execute(
            "SELECT COUNT(*) FROM authority_external_effect WHERE project_id=%s",
            [orphan.project_id],
        )
        effect_count = int(uow.cursor.fetchone()[0])

    assert lineage[0][0:2] == ("future-1", "1")
    assert lineage[0][3:] == ("", "SUCCEEDED")
    assert [row[1] for row in lineage if row[0] == "future-1"] == ["1"]
    assert lineage[1] == (
        "future-2",
        "1",
        orphan.evaluation_operation_id,
        "",
        "CANCELLED",
    )
    assert lineage[2] == (
        "future-2",
        "2",
        replacement_operation_id,
        orphan.evaluation_operation_id,
        "READY",
    )
    assert effect_count == 0


@dataclass(frozen=True, slots=True)
class _CheckpointedSearchOrphan:
    opening: PostgresBookOpeningApplication
    principal: Principal
    opening_run_id: str
    project_id: str
    book_search_id: str


def _create_checkpointed_search_orphan() -> _CheckpointedSearchOrphan:
    harness = CapabilityPackPostgresHarness(
        "book-opening-checkpoint-resume",
        application_build_id=RELEASE_A_BUILD,
        release_sha=RELEASE_A_SHA,
    )
    _activate_planning_pack(harness)
    project_id = harness.project_id
    workspace_id = harness.workspace_id
    book_id = harness.book_ids[0]
    principal = _principal(project_id)
    generic = _seed_inputs(project_id, book_id)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        for asset_type in ("reader_segment_profile", "reader_contract"):
            asset_id = f"fixture:{project_id}:checkpoint:{asset_type}"
            version_id = f"{asset_id}:v1"
            content = {"book_id": book_id, "role": asset_type}
            uow.cursor.execute(
                """
                INSERT INTO authority_asset(asset_id,project_id,asset_type)
                VALUES (%s,%s,%s)
                """,
                [asset_id, project_id, asset_type],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id,asset_id,version_number,lifecycle,
                    eligibility,governance,content,content_hash,schema_version
                ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,%s)
                """,
                [
                    version_id,
                    asset_id,
                    Jsonb(content),
                    canonical_hash(content),
                    f"{asset_type}.v1",
                ],
            )
        uow.commit()
    planning = StoryPlanningGenerationApplication(
        DATABASE_URL,
        execution_binder=_ExternalEffectPepFixturePlanningBinder(),
        application_build_id=RELEASE_A_BUILD,
        commit_sha=RELEASE_A_SHA,
        allow_scripted_evaluation_fixture=True,
        narrative_evaluator_principal=principal,
    )
    narrative_search = PostgresNarrativeSearchApplication(
        DATABASE_URL,
        planning=planning,
    )
    opening = PostgresBookOpeningApplication(
        DATABASE_URL,
        narrative_search=narrative_search,
        input_resolver=BookProductionInputResolver(
            DATABASE_URL,
            application_build_id=RELEASE_A_BUILD,
            commit_sha=RELEASE_A_SHA,
            allow_scripted_qualification_fixture=True,
        ),
        application_build_id=RELEASE_A_BUILD,
        commit_sha=RELEASE_A_SHA,
    )
    opening_roles = {
        role
        for generator in (
            "book_plan.generate",
            "volume_plan.generate",
            "arc_plan.generate",
        )
        for role in GENERATOR_INPUT_ROLES[generator]
        if role not in {"book_plan", "volume_plan"}
    }
    admission = opening.admit(
        OpenBookProductionRequest(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=principal.principal_id,
            expected_book_version=int(generic["book_version"]),
            production_profile=generic["production_profile"],
            planning_input_versions={role: generic[role] for role in opening_roles},
            arc_logical_keys=("arc:checkpoint-resume",),
            idempotency_key=f"{project_id}:open-book",
            trace_id=f"trace:{project_id}:open-book",
            correlation_id=f"correlation:{project_id}",
            initial_story_state_version=generic["initial_story_state"],
            initial_canon_snapshot_version=generic["initial_canon_snapshot"],
        ),
        principal=principal,
    )
    claim = opening.claim_next_execution(
        worker_id="checkpoint-resume-release-a-worker",
        lease_seconds=60,
        project_id=project_id,
    )
    assert claim is not None

    def crash_after_authoritative_book_search_checkpoint() -> None:
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT evidence_id
                FROM authority_book_opening_semantic_checkpoint
                WHERE opening_run_id=%s
                  AND semantic_work_key='book_plan.generate:book:main'
                """,
                [admission.opening_run_id],
            )
            row = uow.cursor.fetchone()
        if row is not None:
            raise SimulatedBookOpeningProcessLoss(
                "opening process disappeared after the Book search checkpoint"
            )

    original_open = opening._open_frozen

    def open_with_checkpoint_crash(
        request: OpenBookProductionRequest, **kwargs: object
    ):
        worker_probe = kwargs.get("execution_probe")

        def combined_probe() -> None:
            if callable(worker_probe):
                worker_probe()
            crash_after_authoritative_book_search_checkpoint()

        kwargs["execution_probe"] = combined_probe
        return original_open(request, **kwargs)

    with (
        patch.object(opening, "_open_frozen", new=open_with_checkpoint_crash),
        pytest.raises(SimulatedBookOpeningProcessLoss),
    ):
        execute_book_opening_claim(
            RuntimeJobAuthority(DATABASE_URL),
            opening,
            principal,
            claim,
            lease_seconds=60,
        )

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT checkpoint.evidence_id,search.status,
                   COUNT(effect.external_effect_id)
            FROM authority_book_opening_semantic_checkpoint AS checkpoint
            JOIN authority_story_narrative_search AS search
              ON search.search_id=checkpoint.evidence_id
             AND search.project_id=%s
            LEFT JOIN authority_external_effect AS effect
              ON effect.project_id=search.project_id
            WHERE checkpoint.opening_run_id=%s
              AND checkpoint.semantic_work_key='book_plan.generate:book:main'
            GROUP BY checkpoint.evidence_id,search.status
            """,
            [project_id, admission.opening_run_id],
        )
        checkpoint = uow.cursor.fetchone()
        assert checkpoint is not None
        assert str(checkpoint[1]) == "ACTIVATED"
        assert int(checkpoint[2]) == 0
        uow.cursor.execute(
            """
            UPDATE authority_runtime_job_lease
            SET lease_expires_at=transaction_timestamp()-INTERVAL '1 second'
            WHERE lease_id=%s
            """,
            [claim.lease_id],
        )
        uow.commit()

    loss_key = f"review-blocker-checkpoint-loss:{admission.opening_run_id}"
    loss = opening.recovery.assess_execution_loss(
        admission.opening_run_id,
        idempotency_key=loss_key,
        principal=principal,
    )
    opening.recovery.converge_execution_loss(
        loss.recovery_assessment_id,
        idempotency_key=loss_key,
        principal=principal,
        expected_opening_run_id=admission.opening_run_id,
    )
    return _CheckpointedSearchOrphan(
        opening=opening,
        principal=principal,
        opening_run_id=admission.opening_run_id,
        project_id=project_id,
        book_search_id=str(checkpoint[0]),
    )


def test_recovered_opening_uses_checkpointed_search_without_repeating_semantic_work() -> (
    None
):
    """A durable checkpoint is a resume cursor, not merely recovery evidence."""

    ensure_migrated()
    orphan = _create_checkpointed_search_orphan()
    assessment = orphan.opening.recovery.assess_recovery(
        orphan.opening_run_id,
        idempotency_key=f"review-blocker-checkpoint-assess:{orphan.opening_run_id}",
        principal=orphan.principal,
    )
    receipt = orphan.opening.recovery.recover(
        assessment.recovery_assessment_id,
        idempotency_key=f"review-blocker-checkpoint-recover:{orphan.opening_run_id}",
        reason="resume from exact Planning-owned checkpoint evidence",
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    claim = orphan.opening.claim_next_execution(
        worker_id="checkpoint-resume-release-b-worker",
        lease_seconds=60,
        project_id=orphan.project_id,
    )
    assert claim is not None
    assert claim.runtime_job_id == receipt.result["runtime_job_id"]

    original_explore = orphan.opening.narrative_search.explore

    def reject_checkpointed_search_reexecution(
        request: NarrativeSearchRequest, **kwargs: object
    ):
        generation = request.generation
        if (
            generation.generator_operation_name == "book_plan.generate"
            and generation.logical_key == "book:main"
        ):
            raise AssertionError(
                "recovered Opening re-entered completed checkpointed semantic work"
            )
        return original_explore(request, **kwargs)

    with patch.object(
        orphan.opening.narrative_search,
        "explore",
        side_effect=reject_checkpointed_search_reexecution,
    ):
        result = execute_book_opening_claim(
            RuntimeJobAuthority(DATABASE_URL),
            orphan.opening,
            orphan.principal,
            claim,
            lease_seconds=60,
        )

    assert result["search_ids"][0] == orphan.book_search_id
    assert orphan.opening.require(orphan.opening_run_id)["lifecycle"] == "COMPLETE"
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            "SELECT COUNT(*) FROM authority_external_effect WHERE project_id=%s",
            [orphan.project_id],
        )
        assert int(uow.cursor.fetchone()[0]) == 0
