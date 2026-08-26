from __future__ import annotations

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.content_authority import (
    CONTENT_CODECS,
    ContentAuthorityApplication,
    ContentOperationRequest,
)
from novel_forge.modules.story_design_authority import (
    NARRATIVE_QUALIFICATION_SCHEMA_VERSION,
    DesignTransition,
    NarrativeSemanticEvaluationApplication,
    NarrativeSemanticEvaluationCommand,
    PlanningScope,
    PostgresStoryDesignAssetAuthority,
    StoryDesignTransitionCommand,
    required_qualification_profiles,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.foundation_repositories import (
    require_current_foundation_set,
)
from tests.integration.capability_pack_postgres_support import (
    CapabilityPackPostgresHarness,
)
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.authority_postgres_support import transaction
from tests.integration.hierarchy_closure_postgres_support import (
    seed_ready_story_foundation,
)
from tests.integration.test_core_functional_loops_postgres import (
    RELEASE_SHA,
    _principal,
)


def _operator_foundation_evaluation(generator_operation_name: str) -> dict:
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
                            "Independent integration operator review binds this "
                            f"criterion to the exact immutable Foundation candidate: {criterion}."
                        ),
                        "evidence_refs": [
                            f"operator-review:{profile.layer.value}:{criterion}"
                        ],
                        "repair_directive": "",
                    }
                    for criterion in profile.criteria
                ],
            }
            for profile in required_qualification_profiles(generator_operation_name)
        ],
    }


def test_operator_authored_foundation_uses_independent_semantic_authority() -> None:
    harness = CapabilityPackPostgresHarness("operator-foundation")
    project_id = harness.project_id
    workspace_id = harness.workspace_id
    book_id = harness.book_ids[0]
    generator = "creative.candidates.generate"
    logical_key = "foundation:creative_foundation:operator-v1"
    candidate_content = {
        "schema_version": "story_design.authority.v1",
        "project_id": project_id,
        "generator_operation_name": generator,
        "planning_scope": "NOT_APPLICABLE",
        "logical_key": logical_key,
        "operator_authored": True,
        "provider_generated": False,
        "candidate_payload": {
            "objective": "Establish a causal public-truth mystery Foundation.",
            "target_reader": "adult speculative mystery readers",
            "why_worth_writing": "Public truth creates personal responsibility.",
            "genre": "speculative mystery",
            "subgenre": "institutional mystery",
            "core_desire": "restore erased belonging",
            "core_fear": "truth will expose the people it should protect",
            "core_conflict": "witnesses challenge a self-editing archive",
            "narrative_engine": "each anomaly forces disclosure or concealment",
            "differentiation": "geography changes through accountable choices",
            "emotional_contract": "wonder becomes costly shared responsibility",
            "serialization_potential": "each district exposes a distinct bargain",
        },
    }
    author = harness.principal(
        "foundation-author",
        "content.authority.execute",
        "content.operation:story_design.candidate.author",
        "story_design.authority.execute",
    )
    reviewer = harness.principal(
        "foundation-reviewer",
        "content.authority.execute",
        "content.operation:story_design.review.author",
        "narrative_design.evaluate",
    )
    content = ContentAuthorityApplication(
        DATABASE_URL,
        application_build_id="operator-foundation-integration",
        commit_sha=RELEASE_SHA,
        integration_proven=CONTENT_CODECS,
        trusted_only=True,
    )
    authored = content.execute(
        ContentOperationRequest(
            definition_name="story_design.candidate.author",
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id=author.principal_id,
            trace_id=f"trace:{project_id}:operator-foundation",
            correlation_id=f"correlation:{project_id}:operator-foundation",
            idempotency_key=f"{logical_key}:author",
            payload={"content": candidate_content},
        ),
        principal=author,
    )
    authority = PostgresStoryDesignAssetAuthority(
        DATABASE_URL,
        application_build_id="operator-foundation-integration",
        commit_sha=RELEASE_SHA,
    )
    state: dict = {"version": 0}

    def transition(
        step: DesignTransition,
        *,
        evidence: dict,
    ) -> dict:
        return authority.transition(
            StoryDesignTransitionCommand(
                project_id=project_id,
                workspace_id=workspace_id,
                actor_id=author.principal_id,
                trace_id=f"trace:{project_id}:operator-foundation",
                correlation_id=f"correlation:{project_id}:operator-foundation",
                idempotency_key=f"{authored.asset_version_id}:{step.value}",
                asset_version_id=authored.asset_version_id,
                content_hash=authored.content_hash,
                logical_key=logical_key,
                generator_operation_name=generator,
                transition=step,
                planning_scope=PlanningScope.NOT_APPLICABLE,
                expected_version=int(state["version"]),
                source_kind="OPERATOR_AUTHORED",
                evidence=evidence,
            ),
            principal=author,
        )

    state = transition(
        DesignTransition.ENROLL,
        evidence={
            "operation_id": authored.operation_id,
            "authoring_operation_id": authored.operation_id,
            "operator_authored": True,
            "provider_generated": False,
        },
    )
    state = transition(DesignTransition.MATERIALIZE, evidence={"passed": True})
    state = transition(
        DesignTransition.STRUCTURAL_VALIDATE,
        evidence={"passed": True, "validator": "story-design-authority"},
    )
    evaluation = _operator_foundation_evaluation(generator)
    review = content.execute(
        ContentOperationRequest(
            definition_name="story_design.review.author",
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id=reviewer.principal_id,
            trace_id=f"trace:{project_id}:operator-foundation-review",
            correlation_id=f"correlation:{project_id}:operator-foundation",
            idempotency_key=f"{authored.asset_version_id}:operator-review",
            payload={
                "candidate_asset_version_id": authored.asset_version_id,
                "candidate_content_hash": authored.content_hash,
                "evaluation": evaluation,
                "review_rationale": (
                    "Independent operator reviewed every declared criterion against "
                    "the frozen candidate; this is design evidence, not human preference."
                ),
            },
            input_assets=(
                {
                    "asset_version_id": authored.asset_version_id,
                    "content_hash": authored.content_hash,
                },
            ),
        ),
        principal=reviewer,
    )
    semantic = NarrativeSemanticEvaluationApplication(
        DATABASE_URL,
        application_build_id="operator-foundation-integration",
        commit_sha=RELEASE_SHA,
        allow_scripted_fixture=False,
    ).execute(
        NarrativeSemanticEvaluationCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=reviewer.principal_id,
            candidate_asset_version_id=authored.asset_version_id,
            generation_operation_id=authored.operation_id,
            generator_operation_name=generator,
            candidate_content_hash=authored.content_hash,
            evaluator_execution_class="OPERATOR_REVIEW",
            evaluation=evaluation,
            evidence_asset_version_ids=(review.asset_version_id,),
            idempotency_key=f"{authored.asset_version_id}:semantic-evaluation",
            trace_id=f"trace:{project_id}:operator-foundation-evaluation",
            correlation_id=f"correlation:{project_id}:operator-foundation",
        ),
        principal=reviewer,
        caller_permission="story_design.authority.execute",
    )
    state = transition(
        DesignTransition.SEMANTIC_VALIDATE,
        evidence={
            "passed": True,
            "evaluation_asset_version_id": (
                semantic.lineage.evaluation_asset_version_id
            ),
            "qualification_hash": semantic.qualification.qualification_hash,
        },
    )
    for step in (
        DesignTransition.QUALIFY,
        DesignTransition.SUBMIT_APPROVAL,
        DesignTransition.APPROVE,
        DesignTransition.ACTIVATE,
    ):
        state = transition(step, evidence={"passed": True})

    assert state["lifecycle"] == "ACTIVE"
    assert state["qualification"] == "QUALIFIED"
    assert state["approval"] == "APPROVED"
    assert state["source_kind"] == "OPERATOR_AUTHORED"
    assert semantic.lineage.evaluator_execution_class == "OPERATOR_REVIEW"
    assert semantic.lineage.provider_model_call_asset_version_id == ""
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT version.content, generation.actor_id, evaluation.actor_id,
                   COUNT(qualification.qualification_id)
            FROM authority_asset_version AS version
            JOIN authority_narrative_design_qualification AS qualification
              ON qualification.evaluation_asset_version_id=version.asset_version_id
            JOIN authority_operation AS generation
              ON generation.operation_id=qualification.generation_operation_id
            JOIN authority_operation AS evaluation
              ON evaluation.operation_id=qualification.evaluation_operation_id
            WHERE version.asset_version_id=%s
            GROUP BY version.content, generation.actor_id, evaluation.actor_id
            """,
            [semantic.lineage.evaluation_asset_version_id],
        )
        evaluation_content, generation_actor, evaluation_actor, receipt_count = (
            uow.cursor.fetchone()
        )
        uow.cursor.execute(
            "SELECT content FROM authority_asset_version WHERE asset_version_id=%s",
            [review.asset_version_id],
        )
        review_content = dict(uow.cursor.fetchone()[0])
    assert str(generation_actor) == author.principal_id
    assert str(evaluation_actor) == reviewer.principal_id
    assert generation_actor != evaluation_actor
    assert int(receipt_count) == len(required_qualification_profiles(generator))
    assert dict(evaluation_content)["provider_execution"] == {}
    assert review_content["human_preference_evidence"] is False
    assert review_content["ground_truth_claimed"] is False
    assert review_content["provider_evidence_claimed"] is False


def test_story_formation_is_durable_qualified_and_reference_only() -> None:
    harness = CapabilityPackPostgresHarness("hierarchy-formation")
    project_id = harness.project_id
    book_id = harness.book_ids[0]
    result = seed_ready_story_foundation(
        DATABASE_URL,
        project_id=project_id,
        workspace_id=harness.workspace_id,
        book_id=book_id,
        principal=_principal(project_id),
        target_chapters=6,
        release_sha=RELEASE_SHA,
        full_story_design_lifecycle=True,
        exercise_formation_recovery=True,
    )

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT lifecycle,current_stage,foundation_set_digest,
                   book_design_asset_version_id,book_design_content_hash
            FROM authority_story_formation_run
            WHERE formation_run_id=%s
            """,
            [result["formation_run_id"]],
        )
        assert uow.cursor.fetchone() == (
            "READY",
            "COMPLETE",
            result["foundation_set_digest"],
            result["book_design_asset_version_id"],
            result["book_design_content_hash"],
        )
        uow.cursor.execute(
            """
            SELECT stage,status
            FROM authority_story_formation_stage
            WHERE formation_run_id=%s
            ORDER BY created_at,stage
            """,
            [result["formation_run_id"]],
        )
        stages = dict(uow.cursor.fetchall())
        assert stages == {
            "CREATIVE_SEARCH": "ACTIVE",
            "CREATIVE_FOUNDATION": "ACTIVE",
            "THEME_CONTRACT": "ACTIVE",
            "ENDING_INTENT": "ACTIVE",
            "READER_PROMISE": "ACTIVE",
            "WORLD_BIBLE": "ACTIVE",
            "CHARACTER_CAST": "ACTIVE",
            "BOOK_DESIGN": "ACTIVE",
        }
        uow.cursor.execute(
            """
            SELECT COUNT(*),COUNT(DISTINCT foundation_role),
                   COUNT(DISTINCT set_generation)
            FROM authority_book_foundation_binding
            WHERE project_id=%s AND book_id=%s AND freshness='CURRENT'
            """,
            [project_id, book_id],
        )
        assert uow.cursor.fetchone() == (6, 6, 1)
        uow.cursor.execute(
            """
            SELECT lifecycle,qualification,approval,planning_scope
            FROM authority_story_design_version_state
            WHERE project_id=%s
              AND asset_version_id=ANY(%s)
            """,
            [project_id, list(result["asset_versions"].values())],
        )
        design_states = uow.cursor.fetchall()
        assert len(design_states) == 6
        assert set(design_states) == {
            ("ACTIVE", "QUALIFIED", "APPROVED", "NOT_APPLICABLE")
        }
        uow.cursor.execute(
            """
            SELECT content
            FROM authority_asset_version
            WHERE asset_version_id=%s
            """,
            [result["book_design_asset_version_id"]],
        )
        book_design = dict(uow.cursor.fetchone()[0])
        uow.cursor.execute(
            """
            SELECT status,attempt_count
            FROM authority_runtime_job
            WHERE job_kind='STORY_FORMATION_ADVANCE'
              AND subject_id=%s
            """,
            [result["formation_run_id"]],
        )
        jobs = uow.cursor.fetchall()

    assert book_design["schema_version"] == "book-design.v5"
    assert (
        book_design["foundation_set"]["set_digest"] == result["foundation_set_digest"]
    )
    assert "rules" not in book_design
    assert "characters" not in book_design
    assert result["formation_replayed"] is True
    assert result["formation_recovery_exercised"] is True
    assert jobs and {status for status, _attempts in jobs} == {
        "SUCCEEDED",
        "CANCELLED",
    }
    assert sum(status == "CANCELLED" for status, _attempts in jobs) == 1
    assert all(int(attempts) == 1 for _status, attempts in jobs)

    with pytest.raises(KernelError, match="FOUNDATION_FORMATION_NOT_READY"):
        with transaction() as _connection, _connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE authority_story_formation_run
                SET lifecycle='WAITING_APPROVAL', current_stage='BOOK_DESIGN'
                WHERE formation_run_id=%s
                """,
                [result["formation_run_id"]],
            )
            require_current_foundation_set(
                cursor,
                project_id=project_id,
                book_id=book_id,
                require_ready=True,
            )

    with pytest.raises(KernelError, match="FOUNDATION_SET_MIXED_GENERATION"):
        with transaction() as _connection, _connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE authority_book_foundation_binding
                SET set_generation=set_generation+1
                WHERE project_id=%s AND book_id=%s
                  AND foundation_role='CHARACTER_CAST'
                  AND freshness='CURRENT'
                """,
                [project_id, book_id],
            )
            require_current_foundation_set(
                cursor,
                project_id=project_id,
                book_id=book_id,
                require_ready=True,
            )
