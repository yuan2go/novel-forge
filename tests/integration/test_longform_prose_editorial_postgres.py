from __future__ import annotations

from dataclasses import replace

import pytest

from novel_forge.modules.book_authority.completion import (
    PostgresBookCompletionAuthority,
)
from novel_forge.modules.book_authority.editorial import BookEditorialWorkflow
from novel_forge.modules.book_followup_authority.application import (
    BookFollowupAuthorityApplication,
)
from novel_forge.modules.book_followup_authority.prose_coordinator import (
    BookProseReviewCoordinator,
)
from novel_forge.modules.book_followup_authority.prose_review import PROSE_DIMENSIONS
from novel_forge.modules.chapter_authority.model_effects import ModelProviderResult
from novel_forge.modules.command_kernel.errors import KernelError
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
)
from tests.integration import (
    test_book_to_chapter_authority_vertical_postgres as scripted_book,
)


class ProseFixturePort:
    external_effect_backed = True
    calls = 0
    database_url = DATABASE_URL
    include_finding = False

    def invoke(
        self, request, *, stage, payload, reservation_tokens, pre_send_assertion=None
    ):
        self.calls += 1
        source = request.require_input("longform_prose_review_window").content
        assert stage == "longform_prose_review"
        assert source["window"]["spans"][0]["text"]
        return ModelProviderResult(
            output={
                "schema_version": "longform-prose-review.v1",
                "manifest_digest": source["manifest_digest"],
                "window_id": source["window"]["window_id"],
                "reviewed_dimensions": list(PROSE_DIMENSIONS),
                "findings": [
                    {
                        "lineage_id": "fixture-motive",
                        "dimension": "motivation_cost",
                        "judgment": "INSUFFICIENT_EVIDENCE",
                        "severity": "NONE",
                        "confidence": 0.6,
                        "claim": "测试需核对未来动机安排",
                        "rationale": "局部证据不能批准计划修改",
                        "evidence": [
                            {
                                "asset_version_id": source["window"]["spans"][0][
                                    "asset_version_id"
                                ],
                                "text_hash": source["window"]["spans"][0]["text_hash"],
                                "start": source["window"]["spans"][0]["start"],
                                "end": source["window"]["spans"][0]["start"] + 2,
                                "quote": source["window"]["spans"][0]["text"][:2],
                            }
                        ],
                    }
                ]
                if self.include_finding
                else [],
            },
            provider_id="fixture",
            model_id="fixture",
            prompt_version="fixture.v1",
            skill_version="fixture.v1",
            input_tokens=1,
            output_tokens=1,
            cost_amount="0",
            currency="USD",
            real_model_call=False,
        )


def metadata(prefix):
    return {
        "idempotency_key": identifier(prefix),
        "trace_id": identifier("trace"),
        "correlation_id": identifier("correlation"),
    }


def test_native_prose_review_durable_resume_and_editorial_policy():
    ensure_migrated()
    helper = scripted_book.BookToChapterAuthorityVerticalPostgresTests()
    try:
        fixture = helper._new_book_fixture(target_chapter_count=2)
        delegated = fixture["authority"].submit_chapter(
            helper._chapter_command(fixture, chapter_number=1),
            principal=fixture["principal"],
        )
        helper._run_child(fixture, delegated["chapter_root_operation_id"])
        fixture["authority"].reconcile_chapter(delegated["chapter_request_id"])
        fixture["authority"].accept_chapter(
            delegated["chapter_request_id"], principal=fixture["principal"]
        )
        principal = replace(
            fixture["principal"],
            authentication_source="server_configuration",
            permissions=frozenset(
                {"book.authority.execute", "book.authority.query", "book.followup:*"}
            ),
        )
        scope = dict(
            project_id=fixture["project_id"],
            workspace_id="workspace:" + fixture["project_id"],
            book_run_id=fixture["book"].book_run_id,
            principal=principal,
        )
        model = ProseFixturePort()
        followup = BookFollowupAuthorityApplication(
            DATABASE_URL,
            application_build_id="prose-test",
            commit_sha="e" * 40,
            prose_model_port=model,
        )
        coordinator = BookProseReviewCoordinator(followup)
        create = metadata("prose")

        def response_loss(point):
            if point == "after_operation_completion_before_response":
                raise RuntimeError("review response lost")

        with pytest.raises(RuntimeError, match="review response lost"):
            coordinator.start(
                **scope,
                **create,
                policy={
                    "policy_version": "v1",
                    "window_codepoints": 512,
                    "overlap_codepoints": 32,
                    "context_token_budget": 4000,
                    "maximum_windows": 20,
                },
                fault_injector=response_loss,
            )
        run = coordinator.start(
            **scope,
            **create,
            policy={
                "policy_version": "v1",
                "window_codepoints": 512,
                "overlap_codepoints": 32,
                "context_token_budget": 4000,
                "maximum_windows": 20,
            },
        )
        assert (
            coordinator.start(
                **scope,
                **create,
                policy={
                    "policy_version": "v1",
                    "window_codepoints": 512,
                    "overlap_codepoints": 32,
                    "context_token_budget": 4000,
                    "maximum_windows": 20,
                },
            )["run_id"]
            == run["run_id"]
        )
        progress = coordinator.report(**scope, run_id=run["run_id"])
        assert not progress["coverage_complete"]
        paused = coordinator.control(
            **scope,
            run_id=run["run_id"],
            expected_version=0,
            paused=True,
            reason="budget review",
            **metadata("pause"),
        )
        with pytest.raises(KernelError, match="resume"):
            coordinator.advance(
                **scope,
                run_id=run["run_id"],
                expected_version=paused["expected_version"],
                **metadata("blocked-advance"),
            )
        coordinator.control(
            **scope,
            run_id=run["run_id"],
            expected_version=paused["expected_version"],
            paused=False,
            reason="same frozen allowance",
            **metadata("resume"),
        )
        progress = coordinator.report(**scope, run_id=run["run_id"])
        while not progress["review_complete"]:
            progress = coordinator.advance(
                **scope,
                run_id=run["run_id"],
                expected_version=progress["expected_version"],
                **metadata("advance"),
            )
        assert (
            progress["source_current"]
            and progress["operations"][0]["report_asset_version_id"]
        )
        assert progress["independent_human_review"] == "NOT_RUN"
        calls = model.calls
        model.include_finding = True
        coordinator.advance(
            **scope,
            run_id=run["run_id"],
            expected_version=progress["expected_version"],
            **metadata("resume"),
        )
        assert model.calls == calls
        source = progress["manifest"]["sources"][0]
        expanded = coordinator.start(
            **scope,
            **metadata("cross-window"),
            policy=progress["manifest"]["policy"],
            evidence_ranges=[
                {"asset_version_id": source["asset_version_id"], "start": 0, "end": 4},
                {"asset_version_id": source["asset_version_id"], "start": 4, "end": 8},
            ],
        )
        expanded_progress = coordinator.report(**scope, run_id=expanded["run_id"])
        assert (
            expanded_progress["coverage_complete"]
            and not expanded_progress["review_complete"]
        )
        assert all(
            operation["source_run_id"] == run["run_id"]
            for operation in expanded_progress["operations"]
        )
        coordinator.advance(
            **scope,
            run_id=expanded["run_id"],
            expected_version=expanded_progress["expected_version"],
            **metadata("cross-verify"),
        )
        assert model.calls == calls + 1
        _assert_native_plan_consumer(coordinator, scope, expanded["run_id"])
        drifted = BookProseReviewCoordinator(
            BookFollowupAuthorityApplication(
                DATABASE_URL,
                application_build_id="prose-changed",
                commit_sha="f" * 40,
                prose_model_port=model,
            )
        )
        current = coordinator.report(**scope, run_id=expanded["run_id"])
        assert (
            drifted.report(**scope, run_id=expanded["run_id"])["implementation_current"]
            is False
        )
        with pytest.raises(KernelError, match="changed manuscript or implementation"):
            drifted.control(
                **scope,
                run_id=expanded["run_id"],
                expected_version=current["expected_version"],
                paused=False,
                reason="must refreeze changed implementation",
                **metadata("drift-resume"),
            )
        completion = PostgresBookCompletionAuthority(
            DATABASE_URL, application_build_id="prose-test", commit_sha="e" * 40
        )
        editorial = BookEditorialWorkflow(completion)
        policy_command = {
            **scope,
            **metadata("policy"),
            "expected_version": 0,
            "kind": "POLICY",
            "content": {
                "policy": {
                    "policy_version": "v1",
                    "enabled": False,
                    "authorized_reviewers": [principal.principal_id],
                    "minimum_signatures": 1,
                    "allow_minor_exceptions": False,
                },
                "approval_rationale": "测试 inactive 政策；不代表真人签署",
            },
        }
        policy = editorial.record(**policy_command)
        assert editorial.record(**policy_command)["event_id"] == policy["event_id"]
        assert editorial.history(**scope)["expected_version"] == 1
        with pytest.raises(KernelError, match="exact Book scope"):
            coordinator.report(
                **{**scope, "book_run_id": "another-book"}, run_id=run["run_id"]
            )
        from novel_forge.modules.authority_security import PrincipalType

        with pytest.raises(PermissionError, match="human operator"):
            editorial.record(
                **{
                    **policy_command,
                    "principal": replace(
                        principal, principal_type=PrincipalType.WORKER
                    ),
                }
            )
        from novel_forge.storage.authority_asset_store import AuthorityAssetQuery

        plan2 = AuthorityAssetQuery(DATABASE_URL).require(
            project_id=scope["project_id"],
            asset_version_id=f"{scope['project_id']}:chapter-plan-v2",
        )
        candidate2 = {
            **next(
                item
                for item in fixture["candidates"]
                if item["asset_type"] == "chapter_plan"
            ),
            "asset_version_id": plan2.asset_version_id,
            "content_hash": plan2.content_hash,
            "content": plan2.content,
        }
        command2 = replace(
            helper._chapter_command(fixture, chapter_number=2),
            chapter_plan_asset_version_id=plan2.asset_version_id,
            chapter_plan_content_hash=plan2.content_hash,
            context_candidates=tuple(
                candidate2 if item["asset_type"] == "chapter_plan" else item
                for item in fixture["candidates"]
            ),
        )
        second = fixture["authority"].submit_chapter(
            command2, principal=fixture["principal"]
        )
        helper._run_child(fixture, second["chapter_root_operation_id"])
        fixture["authority"].reconcile_chapter(second["chapter_request_id"])
        fixture["authority"].accept_chapter(
            second["chapter_request_id"], principal=fixture["principal"]
        )
        stale = coordinator.report(**scope, run_id=run["run_id"])
        assert not stale["source_current"]
        with pytest.raises(KernelError, match="changed manuscript"):
            coordinator.advance(
                **scope,
                run_id=run["run_id"],
                expected_version=stale["expected_version"],
                **metadata("stale-advance"),
            )
        incremental = coordinator.start(
            **scope, policy=progress["manifest"]["policy"], **metadata("incremental")
        )
        incremental_progress = coordinator.report(**scope, run_id=incremental["run_id"])
        assert (
            incremental_progress["source_current"]
            and incremental_progress["completed_window_ids"]
        )
        assert not incremental_progress["coverage_complete"]
        with pytest.raises(KernelError, match="reload editorial"):
            editorial.record(**{**policy_command, **metadata("stale")})
    finally:
        helper.doCleanups()


def _assert_native_plan_consumer(coordinator, scope, run_id):
    from tests.integration.test_hierarchical_planning_postgres import (
        HierarchicalPlanningPostgresTests,
    )
    from tests.integration.test_plan_change_authority_postgres import (
        PlanChangeAuthorityPostgresTests,
    )
    from tests.integration.hierarchy_closure_postgres_support import (
        seed_ready_story_foundation,
    )
    from novel_forge.modules.story_design_authority import (
        PostgresStoryDesignAssetAuthority,
    )
    from novel_forge.modules.hierarchical_planning import (
        PostgresHierarchicalPlanningAuthority,
    )
    from novel_forge.modules.plan_change_authority import PostgresPlanChangeAuthority

    principal = replace(
        scope["principal"],
        permissions=scope["principal"].permissions | {"story_design.authority.execute"},
    )
    scope = {**scope, "principal": principal}
    hierarchy = HierarchicalPlanningPostgresTests()
    hierarchy.project_id = scope["project_id"]
    hierarchy.book_id = "book:" + scope["project_id"]
    hierarchy.principal = principal
    hierarchy.counter = 0
    hierarchy.story_design = PostgresStoryDesignAssetAuthority(
        DATABASE_URL, application_build_id="prose-test", commit_sha="e" * 40
    )
    hierarchy.planning = PostgresHierarchicalPlanningAuthority(
        DATABASE_URL, application_build_id="prose-test", commit_sha="e" * 40
    )
    hierarchy.foundation_result = seed_ready_story_foundation(
        DATABASE_URL,
        project_id=hierarchy.project_id,
        workspace_id=scope["workspace_id"],
        book_id=hierarchy.book_id,
        principal=principal,
        target_chapters=100,
        release_sha="e" * 40,
    )
    hierarchy._seed_realization_authority_inputs()
    plans = PlanChangeAuthorityPostgresTests()
    plans.planning_fixture = hierarchy
    plans.project_id = hierarchy.project_id
    plans.book_id = hierarchy.book_id
    plans.principal = principal
    plans.story_design = hierarchy.story_design
    plans.planning = hierarchy.planning
    target = hierarchy._activate_and_bind(
        plans._book_type(), "book:main", execution_scope=plans._frozen_scope()
    )
    proposed = plans._approved_candidate(
        logical_key="book:main", extra={"objective": "动机待核对后推进城门救援"}
    )
    plan_change = PostgresPlanChangeAuthority(
        DATABASE_URL,
        story_design=hierarchy.story_design,
        planning=hierarchy.planning,
        application_build_id="prose-test",
        commit_sha="e" * 40,
    )
    progress = coordinator.report(**scope, run_id=run_id)
    finding = progress["findings"][0]
    command = {
        **scope,
        **metadata("plan-confirm"),
        "run_id": run_id,
        "expected_version": progress["expected_version"],
        "lineage_id": finding["lineage_id"],
        "finding_digest": finding["finding_digest"],
        "target_asset_version_id": target["asset_version_id"],
        "proposed_asset_version_id": proposed,
        "rationale": "测试确认仅形成提案；不代表真实作者批准",
    }
    preview = coordinator.impact_preview(plan_change=plan_change, **command)
    assert preview["proposal_created"] is False
    assert preview["semantic_impact"]["needs_review"][0]["plan_positions"]
    assert (
        coordinator.report(**scope, run_id=run_id)["expected_version"]
        == progress["expected_version"]
    )
    result = coordinator.propose_plan_change(plan_change=plan_change, **command)
    assert result["proposal"]["status"] == "PENDING_APPROVAL"
    assert result["semantic_impact"] == preview["semantic_impact"]
    assert result["plan_activation_performed"] is False
    assert (
        coordinator.propose_plan_change(plan_change=plan_change, **command)["proposal"][
            "proposal_id"
        ]
        == result["proposal"]["proposal_id"]
    )
    with pytest.raises(KernelError, match="changed targets"):
        coordinator.propose_plan_change(
            plan_change=plan_change,
            **{**command, "proposed_asset_version_id": "different"},
        )


def test_prose_window_uses_real_external_effect_and_materialized_provider_inputs(
    tmp_path,
):
    from pathlib import Path
    from novel_forge.api.authority_dependencies import (
        build_production_execution_composition,
        build_longform_prose_review_model_port,
    )
    from novel_forge.infrastructure.settings import IndustrialSettings
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    ensure_migrated()
    helper = scripted_book.BookToChapterAuthorityVerticalPostgresTests()
    try:
        fixture = helper._new_book_fixture(target_chapter_count=1)
        delegated = fixture["authority"].submit_chapter(
            helper._chapter_command(fixture, chapter_number=1),
            principal=fixture["principal"],
        )
        helper._run_child(fixture, delegated["chapter_root_operation_id"])
        fixture["authority"].reconcile_chapter(delegated["chapter_request_id"])
        fixture["authority"].accept_chapter(
            delegated["chapter_request_id"], principal=fixture["principal"]
        )
        principal = replace(
            fixture["principal"],
            authentication_source="server_configuration",
            permissions=frozenset(
                {"book.authority.execute", "book.authority.query", "book.followup:*"}
            ),
        )
        scope = dict(
            project_id=fixture["project_id"],
            workspace_id="workspace:" + fixture["project_id"],
            book_run_id=fixture["book"].book_run_id,
            principal=principal,
        )
        settings = IndustrialSettings(
            root=Path(__file__).resolve().parents[2],
            environment="development",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
        env = {
            "NOVEL_FORGE_ENVIRONMENT": "development",
            "NOVEL_FORGE_COMMIT_SHA": "e" * 40,
            "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(tmp_path / "objects"),
        }
        execution = build_production_execution_composition(settings, env=env)
        model = build_longform_prose_review_model_port(
            settings, execution=execution, env=env
        )
        followup = BookFollowupAuthorityApplication(
            DATABASE_URL,
            application_build_id="prose-test",
            commit_sha="e" * 40,
            prose_model_port=model,
        )
        coordinator = BookProseReviewCoordinator(followup)
        run = coordinator.start(
            **scope,
            **metadata("effect-prose"),
            policy={
                "policy_version": "effect-v1",
                "window_codepoints": 2048,
                "overlap_codepoints": 64,
                "context_token_budget": 16000,
                "maximum_windows": 3,
            },
        )

        class ReceiptLoss(BaseException):
            pass

        armed = [True]

        def lose_after_receipt(point):
            if point == "after_provider_success" and armed[0]:
                armed[0] = False
                raise ReceiptLoss()

        model.fault_injector = lose_after_receipt
        with pytest.raises(ReceiptLoss):
            coordinator.advance(
                **scope,
                run_id=run["run_id"],
                expected_version=0,
                **metadata("effect-advance"),
            )
        interrupted = coordinator.report(**scope, run_id=run["run_id"])
        operation_id = interrupted["operations"][0]["operation_id"]
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT status FROM authority_external_effect WHERE operation_id=%s",
                [operation_id],
            )
            assert uow.cursor.fetchone()[0] == "SUCCEEDED"
            uow.cursor.execute(
                "UPDATE authority_lease_acquisition lease SET expires_at=acquired_at+INTERVAL '1 microsecond' FROM authority_attempt attempt WHERE lease.attempt_id=attempt.attempt_id AND attempt.operation_id=%s AND lease.status='HELD'",
                [operation_id],
            )
            uow.commit()
        recovery_metadata = metadata("effect-recover")
        progress = coordinator.advance(
            **scope,
            run_id=run["run_id"],
            expected_version=interrupted["expected_version"],
            **recovery_metadata,
        )
        assert progress["operations"][0]["status"] == "SUCCEEDED"
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT status,request_payload FROM authority_external_effect WHERE operation_id=%s",
                [progress["operations"][0]["operation_id"]],
            )
            status, request_payload = uow.cursor.fetchone()
            assert status == "SUCCEEDED"
            assert request_payload["stage"] == "longform_prose_review"
            uow.cursor.execute(
                "SELECT COUNT(*) FROM authority_external_effect_dispatch dispatch JOIN authority_external_effect effect USING(external_effect_id) WHERE effect.operation_id=%s",
                [operation_id],
            )
            assert uow.cursor.fetchone()[0] == 1
            assert (
                request_payload["_production_execution"]["execution_binding_domain"]
                == "longform_prose_review"
            )
    finally:
        helper.doCleanups()
