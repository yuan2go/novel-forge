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
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
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


def _accept_chapter(helper, fixture, number):
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery

    command = helper._chapter_command(fixture, chapter_number=number)
    if number > 1:
        plan = AuthorityAssetQuery(DATABASE_URL).require(
            project_id=fixture["project_id"],
            asset_version_id=f"{fixture['project_id']}:chapter-plan-v{number}",
        )
        command = replace(
            command,
            chapter_plan_asset_version_id=plan.asset_version_id,
            chapter_plan_content_hash=plan.content_hash,
            context_candidates=tuple(
                {
                    **item,
                    "asset_version_id": plan.asset_version_id,
                    "content_hash": plan.content_hash,
                    "content": plan.content,
                }
                if item["asset_type"] == "chapter_plan"
                else item
                for item in fixture["candidates"]
            ),
        )
    delegated = fixture["authority"].submit_chapter(
        command, principal=fixture["principal"]
    )
    helper._run_child(fixture, delegated["chapter_root_operation_id"])
    fixture["authority"].reconcile_chapter(delegated["chapter_request_id"])
    fixture["authority"].accept_chapter(
        delegated["chapter_request_id"], principal=fixture["principal"]
    )


def _automatic_review(
    fixture, *, maximum_windows=20, model=None, relation_window_limit=0,
    window_codepoints=512, relation_retrieval_version=None,
):
    principal = replace(
        fixture["principal"],
        authentication_source="server_configuration",
        permissions=frozenset(
            {"book.authority.execute", "book.authority.query", "book.followup:*"}
        ),
    )
    scope = dict(
        project_id=fixture["project_id"],
        workspace_id=fixture.get("workspace_id", "workspace:" + fixture["project_id"]),
        book_run_id=fixture["book"].book_run_id,
        principal=principal,
    )
    model = model or ProseFixturePort()
    followup = BookFollowupAuthorityApplication(
        DATABASE_URL,
        application_build_id="prose-test",
        commit_sha="e" * 40,
        prose_model_port=model,
    )
    coordinator = BookProseReviewCoordinator(followup)
    run = coordinator.start(
        **scope,
        **metadata("auto-prose"),
        policy={
            "policy_version": "automatic-v1",
            "window_codepoints": window_codepoints,
            "overlap_codepoints": 32,
            "context_token_budget": 4000,
            "maximum_windows": maximum_windows,
            "execution_mode": "AUTOMATIC",
            "follow_acceptance": True,
            "relation_window_limit": relation_window_limit,
            **({"relation_retrieval_version": relation_retrieval_version} if relation_retrieval_version else {}),
        },
    )
    return coordinator, scope, model, run["run_id"]


def test_automatic_review_pause_append_resume_and_incremental_reuse():
    ensure_migrated()
    helper = scripted_book.BookToChapterAuthorityVerticalPostgresTests()
    try:
        fixture = helper._new_book_fixture(target_chapter_count=2)
        _accept_chapter(helper, fixture, 1)
        coordinator, scope, model, run_id = _automatic_review(fixture)
        candidates = coordinator.automatic_candidates(
            principal=scope["principal"], limit=1
        )
        assert [item["run_id"] for item in candidates] == [run_id]
        for _ in range(20):
            coordinator.automatic_tick(**scope, run_id=run_id)
            progress = coordinator.report(**scope, run_id=run_id)
            if progress["review_complete"]:
                break
        assert progress["review_complete"]
        assert (
            coordinator.automatic_candidates(principal=scope["principal"], limit=1)
            == []
        )
        calls = model.calls
        control = coordinator.control(
            **scope,
            run_id=run_id,
            expected_version=progress["expected_version"],
            paused=True,
            reason="wait for next acceptance",
            **metadata("auto-pause"),
        )
        _accept_chapter(helper, fixture, 2)
        assert (
            coordinator.automatic_candidates(principal=scope["principal"], limit=1)
            == []
        )
        assert coordinator.automatic_tick(**scope, run_id=run_id)["status"] == "PAUSED"
        assert model.calls == calls
        coordinator.control(
            **scope,
            run_id=run_id,
            expected_version=control["expected_version"],
            paused=False,
            reason="resume bounded incremental review",
            **metadata("auto-resume"),
        )
        incremental = coordinator.automatic_tick(**scope, run_id=run_id)
        assert incremental["run_id"] != run_id
        new_id = incremental["run_id"]
        assert coordinator.automatic_tick(**scope, run_id=run_id)["run_id"] == new_id
        new_progress = coordinator.report(**scope, run_id=new_id)
        assert len(new_progress["operations"]) == len(progress["operations"])
        assert all(
            item["source_run_id"] == run_id for item in new_progress["operations"]
        )
        for _ in range(20):
            coordinator.automatic_tick(**scope, run_id=new_id)
            new_progress = coordinator.report(**scope, run_id=new_id)
            if new_progress["review_complete"]:
                break
        assert new_progress["review_complete"] and new_progress["source_current"]
        assert model.calls == new_progress["total_windows"]
        assert (
            coordinator.automatic_candidates(principal=scope["principal"], limit=1)
            == []
        )
        assert not new_progress["relation_verification"][
            "global_relationships_verified"
        ]
        assert (
            coordinator.report(**scope, run_id=run_id)["manifest"]
            == progress["manifest"]
        )
    finally:
        helper.doCleanups()


def test_pause_wins_admission_race_without_orphan_ready_review(monkeypatch):

    ensure_migrated()
    helper = scripted_book.BookToChapterAuthorityVerticalPostgresTests()
    try:
        fixture = helper._new_book_fixture(target_chapter_count=1)
        _accept_chapter(helper, fixture, 1)
        coordinator, scope, model, run_id = _automatic_review(fixture)
        original = coordinator._command

        def pause_before_advance(name, *args, **kwargs):
            if name == "book.prose_review.advance":
                coordinator.control(
                    **scope,
                    run_id=run_id,
                    expected_version=0,
                    paused=True,
                    reason="concurrent editorial pause",
                    **metadata("concurrent-pause"),
                )
            return original(name, *args, **kwargs)

        monkeypatch.setattr(coordinator, "_command", pause_before_advance)
        with pytest.raises(KernelError, match="progress changed"):
            coordinator.automatic_tick(**scope, run_id=run_id)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT COUNT(*) FROM authority_operation WHERE project_id=%s AND definition_name='longform.prose_review'",
                [scope["project_id"]],
            )
            assert uow.cursor.fetchone()[0] == 0
        assert model.calls == 0
    finally:
        helper.doCleanups()


def test_paused_prose_is_filtered_before_worker_batch_limit(monkeypatch):
    from novel_forge.modules.content_authority.scheduler import (
        ContentAuthorityScheduler,
    )

    ensure_migrated()
    helper = scripted_book.BookToChapterAuthorityVerticalPostgresTests()
    try:
        fixture = helper._new_book_fixture(target_chapter_count=1)
        _accept_chapter(helper, fixture, 1)
        coordinator, scope, model, run_id = _automatic_review(fixture)
        monkeypatch.setattr(coordinator.followup, "run_or_recover", lambda _: None)
        first = coordinator.automatic_tick(**scope, run_id=run_id)
        first_id = first["operations"][0]["operation_id"]
        coordinator.control(
            **scope,
            run_id=run_id,
            expected_version=first["expected_version"],
            paused=True,
            reason="editorial pause",
            **metadata("fair-pause"),
        )
        second = coordinator.start(
            **scope,
            **metadata("fair-new"),
            policy={
                **first["manifest"]["policy"],
                "policy_version": "separate-review-v2",
            },
        )
        pending = coordinator.automatic_tick(**scope, run_id=second["run_id"])
        second_id = pending["operations"][0]["operation_id"]
        scheduler = ContentAuthorityScheduler(
            DATABASE_URL, registry=coordinator.followup.registry
        )
        blocked = coordinator.blocked_dispatch_operations(
            project_ids=(scope["project_id"],)
        )
        assert first_id in blocked and second_id not in blocked
        ready = scheduler.pending_operations(
            limit=1, project_ids=(scope["project_id"],), excluded_operation_ids=blocked
        )
        assert ready == ((second_id, scope["project_id"]),)
        assert model.calls == 0
    finally:
        helper.doCleanups()


def test_automatic_review_exhausted_window_allowance_stops_scheduling():
    ensure_migrated()
    helper = scripted_book.BookToChapterAuthorityVerticalPostgresTests()
    try:
        fixture = helper._new_book_fixture(target_chapter_count=1)
        _accept_chapter(helper, fixture, 1)
        coordinator, scope, model, run_id = _automatic_review(
            fixture, maximum_windows=1, window_codepoints=64
        )
        progress = coordinator.automatic_tick(**scope, run_id=run_id)
        assert not progress["review_complete"]
        calls = model.calls
        assert (
            coordinator.automatic_tick(**scope, run_id=run_id)["status"]
            == "BUDGET_PAUSED"
        )
        assert (
            coordinator.automatic_candidates(principal=scope["principal"], limit=1)
            == []
        )
        assert model.calls == calls
    finally:
        helper.doCleanups()


def test_automatic_remote_pair_enters_native_plan_disposition_and_located_recheck():
    from psycopg.types.json import Jsonb
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from novel_forge.modules.book_followup_authority.prose_review import (
        completion_digest,
    )

    class PairedReviewPort(ProseFixturePort):
        include_finding = True
        recheck = False

        def invoke(self, request, **kwargs):
            result = super().invoke(request, **kwargs)
            window = request.require_input("longform_prose_review_window").content[
                "window"
            ]
            if not window.get("relation_hypothesis") and not self.recheck:
                result.output["findings"] = []
            else:
                finding = result.output["findings"][0]
                finding.update(
                    judgment="INTENTIONAL" if self.recheck else "ISSUE",
                    severity="NONE" if self.recheck else "MAJOR",
                )
                finding["evidence"] = [
                    {
                        "asset_version_id": span["asset_version_id"],
                        "text_hash": span["text_hash"],
                        "start": span["start"],
                        "end": span["start"] + 2,
                        "quote": span["text"][:2],
                    }
                    for span in window["spans"]
                ]
            return result

    ensure_migrated()
    helper = scripted_book.BookToChapterAuthorityVerticalPostgresTests()
    try:
        fixture = helper._new_book_fixture(target_chapter_count=3)
        project = fixture["project_id"]
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            template = uow.repositories.asset_documents.require(
                project_id=project, asset_version_id=f"{project}:chapter-plan-v2"
            )
            content = {**template.content, "chapter": 3, "title": "The Promise Returns"}
            content["narrative_realization_slice"] = {
                **content["narrative_realization_slice"], "chapter_number": 3
            }
            uow.cursor.execute(
                "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,'chapter_plan')",
                [f"{project}:chapter-plan-3", project],
            )
            uow.cursor.execute(
                "INSERT INTO authority_asset_version(asset_version_id,asset_id,version_number,lifecycle,eligibility,governance,content,content_hash,schema_version) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,'integration-fixture.v1')",
                [
                    f"{project}:chapter-plan-v3",
                    f"{project}:chapter-plan-3",
                    Jsonb(content),
                    completion_digest(content),
                ],
            )
            uow.commit()
        for number in (1, 2, 3):
            _accept_chapter(helper, fixture, number)
        model = PairedReviewPort()
        coordinator, scope, model, run_id = _automatic_review(
            fixture, model=model, relation_window_limit=1
        )
        for _ in range(20):
            progress = coordinator.automatic_tick(**scope, run_id=run_id)
            if progress.get("review_complete"):
                break
        assert progress["review_complete"]
        remote = [
            window
            for window in progress["manifest"]["windows"]
            if window.get("relation_hypothesis")
        ]
        assert len(remote) == 1
        assert [span["chapter_number"] for span in remote[0]["spans"]] == [1, 3]
        assert progress["findings"][0]["status"] == "OPEN"
        _assert_native_plan_consumer(coordinator, scope, run_id)
        original = coordinator.report(**scope, run_id=run_id)
        assert (
            original["findings"][0]["disposition"]["decision"] == "FUTURE_PLAN_PROPOSAL"
        )
        assert (
            original["findings"][0]["disposition"]["resolution_evidence"]["resolution"]
            == "UNRESOLVED"
        )
        model.recheck = True
        recheck = coordinator.start(
            **scope,
            **metadata("remote-recheck"),
            policy=progress["manifest"]["policy"],
            evidence_ranges=[
                {key: span[key] for key in ("asset_version_id", "start", "end")}
                for span in remote[0]["spans"]
            ],
        )
        checked = coordinator.automatic_tick(**scope, run_id=recheck["run_id"])
        assert checked["review_complete"]
        assert checked["findings"][0]["status"] == "CONFLICT_REQUIRES_REVIEW"
        completion = PostgresBookCompletionAuthority(
            DATABASE_URL, application_build_id="prose-test", commit_sha="e" * 40
        )
        BookEditorialWorkflow(completion).record(
            **scope,
            **metadata("remote-policy"),
            expected_version=0,
            kind="POLICY",
            content={
                "policy": {
                    "policy_version": "recheck-v1",
                    "enabled": True,
                    "authorized_reviewers": [scope["principal"].principal_id],
                    "minimum_signatures": 1,
                    "allow_minor_exceptions": False,
                },
                "approval_rationale": "scripted named-reviewer boundary test",
            },
        )
        finding = checked["findings"][0]
        counter = next(
            item for item in checked["operations"] if not item.get("source_run_id")
        )
        disposition = coordinator.disposition(
            **scope,
            **metadata("remote-dismiss"),
            run_id=recheck["run_id"],
            expected_version=checked["expected_version"],
            lineage_id=finding["lineage_id"],
            finding_digest=finding["finding_digest"],
            decision="DISMISSED_WITH_EVIDENCE",
            rationale="fixture counterevidence covers both original locations",
            consumer_asset_version_id=counter["report_asset_version_id"],
        )
        assert (
            disposition["resolution_evidence"]["resolution"]
            == "DISMISSED_BY_AUTHORIZED_REVIEWER"
        )
        assert (
            coordinator.report(**scope, run_id=run_id)["manifest"]
            == original["manifest"]
        )
        assert checked["independent_human_review"] == "NOT_RUN"
    finally:
        helper.doCleanups()


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


@pytest.fixture
def native_prose_effect_window(tmp_path):
    from pathlib import Path
    from novel_forge.api.authority_dependencies import (
        build_production_execution_composition,
        build_longform_prose_review_model_port,
    )
    from novel_forge.infrastructure.settings import IndustrialSettings

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
                {"book.authority.execute", "book.authority.query", "book.followup:*", "external_effect.resolve"}
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
                "execution_mode": "AUTOMATIC",
                "follow_acceptance": True,
            },
        )

        yield dict(helper=helper,fixture=fixture,scope=scope,settings=settings,env=env,execution=execution,model=model,coordinator=coordinator,run=run)
    finally:
        helper.doCleanups()


def test_prose_window_uses_real_external_effect_and_materialized_provider_inputs(native_prose_effect_window):
    values=native_prose_effect_window
    helper,fixture,scope,model,coordinator,run=(values[key] for key in ("helper","fixture","scope","model","coordinator","run"))
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
    _accept_chapter(helper, fixture, 2)
    progress = coordinator.automatic_tick(**scope, run_id=run["run_id"])
    assert progress["operations"][0]["status"] == "SUCCEEDED"
    assert not progress["source_current"]
    assert progress["manifest"] == interrupted["manifest"]
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
    following = coordinator.automatic_tick(**scope, run_id=run["run_id"])
    assert following["run_id"] != run["run_id"]
    assert (
        coordinator.report(**scope, run_id=following["run_id"])["operations"][0][
            "operation_id"
        ]
        == operation_id
    )


@pytest.mark.parametrize('recovery_case',['direct','coordinator','wrong-actor','live-lease','ambiguous','cancelled','query-failed_final','query-cancelled','query-not_found'])
def test_unknown_review_rebuild_queries_original_effect_without_resending(native_prose_effect_window,recovery_case,monkeypatch):
    from novel_forge.api.authority_dependencies import build_production_execution_composition, build_longform_prose_review_model_port
    from novel_forge.modules.book_followup_authority.application import BookFollowupAdmission
    from scripts.book_prose_qualification import WindowResponseLoss, ConsumerRestartRequired, require_unknown_checkpoint

    values = native_prose_effect_window
    scope,settings,env,execution,run = (values[key] for key in ('scope','settings','env','execution','run'))
    coordinator = values['coordinator']
    report = coordinator.report(**scope,run_id=run['run_id'])
    execution.close()
    execution = build_production_execution_composition(settings,env=env)
    fault = WindowResponseLoss(execution.gateway,database_url=DATABASE_URL,
        scope={**{key:value for key,value in scope.items() if key!='principal'},'run_id':run['run_id'],
            'actor_id':scope['principal'].principal_id,'book_id':coordinator._book_id(scope['book_run_id'],scope['project_id']),
            'manifest_digest':report['manifest_digest']},window=report['manifest']['windows'][0])
    model = build_longform_prose_review_model_port(settings,execution=replace(execution,gateway=fault),env=env)
    initial = BookFollowupAuthorityApplication(DATABASE_URL,application_build_id='prose-test',commit_sha='e'*40,prose_model_port=model)
    advance = metadata('unknown-review')
    with pytest.raises((ConsumerRestartRequired,KernelError)) as failure:
        BookProseReviewCoordinator(initial).advance(**scope,run_id=run['run_id'],expected_version=0,**advance)
    assert isinstance(failure.value,ConsumerRestartRequired) or failure.value.code == 'EFFECT_EXTERNAL_STATE_UNKNOWN'
    operation_id = fault.operation_id
    assert fault.triggered and operation_id
    checkpoint = require_unknown_checkpoint(DATABASE_URL,operation_id)
    execution.close()
    rebuilt = build_production_execution_composition(settings,env=env)
    try:
        model = build_longform_prose_review_model_port(settings,execution=rebuilt,env=env)
        followup = BookFollowupAuthorityApplication(DATABASE_URL,application_build_id='prose-test',commit_sha='e'*40,
            prose_model_port=model,worker_id='review-rebuilt')
        admission = BookFollowupAdmission(operation_id,scope['project_id'],True)
        if recovery_case == 'wrong-actor':
            from novel_forge.modules.authority_security.service import PrincipalType
            other = replace(scope['principal'],principal_id='other-author',principal_type=PrincipalType.SERVICE)
            with pytest.raises(PermissionError,match='original result'):
                BookProseReviewCoordinator(followup).advance(**{**scope,'principal':other},run_id=run['run_id'],expected_version=0,**advance)
            require_unknown_checkpoint(DATABASE_URL,operation_id)
            return
        if recovery_case == 'cancelled':
            from novel_forge.modules.command_kernel.cancellation import CancelCommand,request_cancellation
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute('SELECT version,trace_id,correlation_id FROM authority_operation WHERE operation_id=%s',[operation_id])
                version,trace,correlation = uow.cursor.fetchone()
            request_cancellation(DATABASE_URL,CancelCommand(operation_id,scope['project_id'],scope['principal'].principal_id,
                'Cancel the independent test review',version,'cancel:'+operation_id,trace,correlation))
            with pytest.raises(KernelError,match='OPERATION_CANCELLATION_REQUESTED'):
                followup.run_or_recover(admission)
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT count(*) FROM authority_effect_reconciliation_evidence WHERE external_effect_id=%s",[checkpoint['external_effect_id']])
                assert uow.cursor.fetchone()[0] == 0
                uow.cursor.execute("SELECT status FROM authority_attempt WHERE operation_id=%s",[operation_id])
                assert uow.cursor.fetchone()[0] == 'CANCELLED'
            return
        if recovery_case == 'live-lease':
            from novel_forge.modules.command_kernel.attempt_runtime import acquire_attempt_lease
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute('SELECT attempt_id FROM authority_attempt WHERE operation_id=%s',[operation_id])
                attempt_id = uow.cursor.fetchone()[0]
            acquire_attempt_lease(DATABASE_URL,attempt_id=attempt_id,project_id=scope['project_id'],worker_id='other-review-owner',
                lease_seconds=30,trace_id='trace:live-review-owner',correlation_id=run['run_id'])
            with pytest.raises(KernelError,match='CONTENT_RECOVERY_LEASE_ACTIVE'):
                followup.run_or_recover(admission)
            require_unknown_checkpoint(DATABASE_URL,operation_id)
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("UPDATE authority_lease_acquisition SET expires_at=acquired_at+INTERVAL '1 microsecond' WHERE attempt_id=%s AND status='HELD'",[attempt_id])
                uow.commit()
        if recovery_case.startswith('query-'):
            from novel_forge.modules.command_kernel.external_effect_adapters import ProviderResult
            outcome = recovery_case.removeprefix('query-')
            original = rebuilt.gateway.for_recovery
            class TerminalQuery:
                def __init__(self,delegate):self.delegate=delegate
                def __getattr__(self,key):return getattr(self.delegate,key)
                def query(self,**kwargs):return ProviderResult(outcome,'fixture-query-terminal',{'request_sent':outcome!='not_found'})
            monkeypatch.setattr(rebuilt.gateway,'for_recovery',lambda **kwargs:TerminalQuery(original(**kwargs)))
            with pytest.raises(KernelError,match='CONTENT_RECOVERY_TERMINAL') as rejected:
                followup.run_or_recover(admission)
            assert outcome in str(rejected.value)
            expected = {'failed_final':'FAILED_FINAL','cancelled':'CANCELLED','not_found':'FAILED_RETRYABLE'}[outcome]
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute('SELECT status FROM authority_operation WHERE operation_id=%s',[operation_id])
                assert uow.cursor.fetchone()[0] == expected
                uow.cursor.execute('SELECT status,result FROM authority_attempt WHERE operation_id=%s',[operation_id])
                attempt = uow.cursor.fetchone()
                assert attempt[0] == expected and attempt[1]['reconciliation_outcome'] == outcome
                uow.cursor.execute("SELECT status FROM authority_lease_acquisition WHERE attempt_id=(SELECT attempt_id FROM authority_attempt WHERE operation_id=%s) ORDER BY fencing_token DESC LIMIT 1",[operation_id])
                assert uow.cursor.fetchone()[0] == 'RELEASED'
                uow.cursor.execute('SELECT count(*) FROM authority_external_effect_dispatch WHERE external_effect_id=%s',[checkpoint['external_effect_id']])
                assert uow.cursor.fetchone()[0] == 1
                uow.cursor.execute('SELECT outcome FROM authority_effect_reconciliation_evidence WHERE external_effect_id=%s',[checkpoint['external_effect_id']])
                assert uow.cursor.fetchall() == [(outcome,)]
                uow.cursor.execute('SELECT count(*),max(attempt_number) FROM authority_attempt WHERE operation_id=%s',[operation_id])
                assert uow.cursor.fetchone() == (1,1)
            return
        if recovery_case == 'ambiguous':
            from novel_forge.modules.command_kernel.external_effect_adapters import ProviderResult
            original = rebuilt.gateway.for_recovery
            class AmbiguousQuery:
                def __init__(self,delegate):self.delegate=delegate
                def __getattr__(self,key):return getattr(self.delegate,key)
                def query(self,**kwargs):return ProviderResult('ambiguous','fixture-query-unknown',{'remote_outcome':'UNKNOWN'})
            monkeypatch.setattr(rebuilt.gateway,'for_recovery',lambda **kwargs:AmbiguousQuery(original(**kwargs)))
            with pytest.raises(KernelError,match='EXTERNAL_EFFECT_RECONCILIATION_REQUIRED'):
                followup.run_or_recover(admission)
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute('SELECT status FROM authority_external_effect WHERE external_effect_id=%s',[checkpoint['external_effect_id']])
                assert uow.cursor.fetchone()[0] in {'UNKNOWN','RECONCILIATION_REQUIRED'}
                uow.cursor.execute('SELECT status FROM authority_budget_reservation WHERE external_effect_id=%s',[checkpoint['external_effect_id']])
                assert uow.cursor.fetchone()[0] == 'HELD_UNKNOWN'
            monkeypatch.setattr(rebuilt.gateway,'for_recovery',original)
        if recovery_case == 'coordinator':
            ordinary = BookProseReviewCoordinator(followup)
            report = ordinary.advance(**scope,run_id=run['run_id'],expected_version=0,**advance)
            assert report['operations'][0]['operation_id'] == operation_id
            assert report['operations'][0]['status'] == 'SUCCEEDED'
        result = followup.run_or_recover(admission)
        replay = followup.run_or_recover(admission)
        assert result.output.asset_version_id == replay.output.asset_version_id
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute('SELECT status FROM authority_operation WHERE operation_id=%s',[operation_id])
            assert uow.cursor.fetchone()[0] == 'SUCCEEDED'
            uow.cursor.execute("SELECT external_effect_id,status FROM authority_external_effect WHERE operation_id=%s",[operation_id])
            assert uow.cursor.fetchall() == [(checkpoint['external_effect_id'],'SUCCEEDED')]
            uow.cursor.execute("SELECT count(*) FROM authority_external_effect_dispatch WHERE external_effect_id=%s",[checkpoint['external_effect_id']])
            assert uow.cursor.fetchone()[0] == 1
            uow.cursor.execute("SELECT count(*) FROM authority_external_receipt receipt JOIN authority_external_effect_dispatch dispatch USING(dispatch_id) WHERE dispatch.external_effect_id=%s",[checkpoint['external_effect_id']])
            assert uow.cursor.fetchone()[0] == 1
            uow.cursor.execute("SELECT count(*) FROM authority_effect_reconciliation_evidence WHERE external_effect_id=%s AND outcome='success'",[checkpoint['external_effect_id']])
            assert uow.cursor.fetchone()[0] == 1
            uow.cursor.execute("SELECT count(*),max(attempt_number) FROM authority_attempt WHERE operation_id=%s",[operation_id])
            assert uow.cursor.fetchone() == (1,1)
    finally:
        rebuilt.close()


def test_chapter_literal_review_persists_exact_source_binding_and_replays_without_another_effect(native_prose_effect_window):
    from novel_forge.api.authority_dependencies import build_production_execution_composition, build_longform_prose_review_model_port
    from novel_forge.modules.book_followup_authority.prose_review import CHAPTER_LITERAL_CITATION_CONTRACT
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
    values = native_prose_effect_window
    scope = values['scope']
    frozen = values['coordinator'].report(**scope, run_id=values['run']['run_id'])['manifest']
    source_window = frozen['windows'][0]
    span = source_window['spans'][0]
    quote = span['text'][:min(32, len(span['text']))]
    calls = []
    def response(stage, inputs):
        assert stage == 'longform_prose_review'
        calls.append(inputs['window_id'])
        return dict(schema_version='longform-prose-review.v4', manifest_digest=inputs['manifest_digest'], window_id=inputs['window_id'],
                    reviewed_dimensions=list(PROSE_DIMENSIONS), findings=[dict(lineage_id='literal-chapter', dimension='motivation_cost',
                    judgment='INSUFFICIENT_EVIDENCE', severity='NONE', confidence=0.5, claim='局部正文不能证明后续选择', rationale='仅保留给定原句作为待核查观察',
                    evidence=[dict(chapter_number=span['chapter_number'], quote=quote)], repair=dict(root_cause='UNCERTAIN', problem_owner='UNKNOWN',
                    repair_scope='INVESTIGATE', revision_goal='核对后续原文', preserve=['已保存正文'], resolution_criteria=['后续文本支持判断']))])
    execution = build_production_execution_composition(values['settings'], env=values['env'], chapter_fixture_factory=response)
    try:
        model = build_longform_prose_review_model_port(values['settings'], execution=execution, env=values['env'])
        followup = BookFollowupAuthorityApplication(DATABASE_URL, application_build_id='prose-test', commit_sha='e'*40, prose_model_port=model)
        coordinator = BookProseReviewCoordinator(followup)
        policy = {**frozen['policy'], 'policy_version': 'chapter-literal-native.v1', 'diagnosis_contract': 'prose-root-cause.v1',
                  'citation_locator_contract': CHAPTER_LITERAL_CITATION_CONTRACT, 'reading_mode': 'BODY_FIRST',
                  'execution_mode': 'MANUAL', 'follow_acceptance': False}
        run = coordinator.start(**scope, **metadata('chapter-literal-start'), policy=policy)
        command = dict(**scope, **metadata('chapter-literal-advance'), run_id=run['run_id'], expected_version=0)
        progress = coordinator.advance(**command)
        assert progress['review_complete'] and progress['source_current']
        operation = progress['operations'][0]
        assert operation['status'] == 'SUCCEEDED'
        document = AuthorityAssetQuery(DATABASE_URL).require(project_id=scope['project_id'], asset_version_id=operation['report_asset_version_id'])
        citation = document.content['findings'][0]['evidence'][0]
        assert document.content['schema_version'] == 'longform-prose-review.v4'
        assert citation['asset_version_id'] == span['asset_version_id'] and citation['text_hash'] == span['text_hash']
        assert citation['quote'] == quote and citation['start'] == span['start']
        assert coordinator.advance(**command)['review_complete']
        assert len(calls) == 1
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT receipt.payload->'evidence'->'result' FROM authority_external_receipt receipt JOIN authority_external_effect_dispatch dispatch USING(dispatch_id) JOIN authority_external_effect effect USING(external_effect_id) WHERE effect.operation_id=%s", [operation['operation_id']])
            raw = uow.cursor.fetchone()[0]
            assert raw['findings'][0]['evidence'] == [dict(chapter_number=span['chapter_number'], quote=quote)]
    finally:
        execution.close()
