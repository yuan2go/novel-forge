from copy import deepcopy

from psycopg.types.json import Jsonb
import pytest

from novel_forge.api.authority_dependencies import (
    build_chapter_authority_application,
    build_production_execution_composition,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_authority.production import (
    ChapterAuthorityCommandAdapter,
    PostgresBookAuthority,
    StartBookProductionCommand,
    SubmitBookChapterCommand,
)
from novel_forge.modules.book_authority.prose_sources import (
    require_frozen_prose_frontier,
)
from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.chapter_authority.execution_gateway import (
    default_chapter_fixture_response,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.review.diagnostics import prose_hash
from novel_forge.modules.review.prose_window import (
    PRESERVATION_DIMENSIONS,
    WINDOW_POLICY,
    digest,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, identifier
from tests.integration import (
    test_book_to_chapter_authority_vertical_postgres as book_support,
)
from tests.integration import test_postgresql_only_chapter_slice as chapter_support


HISTORY = "沈舟左臂中箭，最后一枚雷符已经耗尽。许霜答应守住东门。"
BROKEN = "沈舟左臂完好，掏出雷符。"
REPAIRED = "沈舟左臂带伤，只能收起空符袋。"


class ReceiptCommitLoss(BaseException):
    pass


class ProseTransport:
    def __init__(self, loss=False):
        self.calls = []
        self.loss = loss
        self.lost = False

    def checkpoint(self, point):
        if (
            self.loss
            and not self.lost
            and point == "after_provider_success"
            and self.calls
            and self.calls[-1][0] == "review"
            and self.calls[-1][1]["cross_chapter_window"]["sources"]
        ):
            self.lost = True
            raise ReceiptCommitLoss()

    def __call__(self, stage, inputs):
        self.calls.append((stage, deepcopy(inputs)))
        result = default_chapter_fixture_response(stage, inputs)
        if stage == "draft":
            sentence = HISTORY if inputs["plan"]["chapter"] == 1 else BROKEN
            result["scene_artifacts"][-1]["text"] += " " + sentence
            result["text"] = "\n\n".join(
                item["text"] for item in result["scene_artifacts"]
            )
        if stage == "review":
            window = inputs["cross_chapter_window"]
            result.update(score=90, issues=[], preservation_checks=[])
            if window["sources"]:
                text = inputs["draft"]["text"]
                start = text.index(BROKEN)
                source = window["sources"][-1]
                prior = source["excerpts"][0]
                source_start = prior["text"].index(HISTORY) + prior["start"]
                result.update(
                    score=60,
                    issues=[
                        {
                            "code": "CAUSAL_CARRYOVER",
                            "category": "CAUSAL_CARRYOVER",
                            "severity": "blocking",
                            "message": "伤势与已耗尽的符箓无因复原",
                            "judgment_kind": "SEMANTIC_CONTRADICTION",
                            "confidence": "HIGH",
                            "interpretation": "CONTINUITY_PROBLEM",
                            "lineage_code": None,
                            "evidence": {
                                "start": start,
                                "end": start + len(BROKEN),
                                "quote": BROKEN,
                                "asset_version_id": inputs[
                                    "target_candidate_asset_version_id"
                                ],
                                "text_hash": prose_hash(text),
                            },
                            "supporting_evidence": [
                                {
                                    **{
                                        key: source[key]
                                        for key in (
                                            "chapter_number",
                                            "asset_version_id",
                                            "content_hash",
                                            "text_hash",
                                        )
                                    },
                                    "start": source_start,
                                    "end": source_start + len(HISTORY),
                                    "quote": HISTORY,
                                    "relation_to_issue": "承接伤势和资源消耗",
                                }
                            ],
                            "violated_constraint": "可见代价的连续性",
                            "revision_goal": "保持伤势与资源后果",
                            "preserve": ["本章任务和其他场景"],
                            "acceptance_criteria": ["不能无因复原伤势或资源"],
                        }
                    ],
                )
        if stage == "revision":
            draft, issues = inputs["draft"], inputs["review"]["issues"]
            result = {
                "text": draft["text"],
                "scene_artifacts": deepcopy(draft["scene_artifacts"]),
                "edits": [],
                "resolved_issue_codes": [],
            }
            if issues:
                issue = issues[0]
                result["text"] = draft["text"].replace(BROKEN, REPAIRED)
                result["scene_artifacts"][-1]["text"] = result["scene_artifacts"][-1][
                    "text"
                ].replace(BROKEN, REPAIRED)
                result["edits"] = [
                    {
                        **{
                            key: issue["evidence_locator"][key]
                            for key in ("start", "end", "quote")
                        },
                        "replacement": REPAIRED,
                        "issue_codes": [issue["code"]],
                    }
                ]
                result["resolved_issue_codes"] = [issue["code"]]
        if stage == "rereview":
            text = inputs["revision"]["text"]
            evidence = {"start": 0, "end": len(text), "quote": text}
            result["resolution_checks"] = [
                {
                    "code": issue["code"],
                    "status": "RESOLVED",
                    "preservation": "PRESERVED",
                    "evidence": evidence,
                    "supporting_evidence": issue["supporting_evidence"],
                    "reason": "修复后保留资源与伤势代价",
                }
                for issue in inputs["review"]["issues"]
            ]
            result["preservation_checks"] = [
                {
                    "dimension": key,
                    "status": "PRESERVED",
                    "evidence": evidence,
                    "reason": "fixture: unrelated prose preserved",
                }
                for key in PRESERVATION_DIMENSIONS
            ]
        return result


def make_book(tmp_path, transport, *, prepare_plans=None):
    from tests.integration.capability_pack_postgres_support import (
        CapabilityPackPostgresHarness,
    )

    harness = CapabilityPackPostgresHarness("cross-chapter", release_sha="e" * 40)
    approved = harness.register_compile_approve(
        "1.0.0",
        generation=1,
        approval_scope=harness.approval_scope(
            environments=("test",), runtime_profiles=("test",)
        ),
        target_runtime_profile="test",
    )
    harness.register_agents(approved.compiled)
    harness.activate(
        harness.deploy(approved, environment="test", runtime_profile="test"),
        environment="test",
    )
    project = harness.project_id
    settings = IndustrialSettings(
        root=tmp_path,
        environment="test",
        storage_authority="postgresql",
        database_url=DATABASE_URL,
    )
    env = {
        "NOVEL_FORGE_ENVIRONMENT": "test",
        "NOVEL_FORGE_COMMIT_SHA": "e" * 40,
        "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
        "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(tmp_path / "objects"),
        "NOVEL_FORGE_AUTHORITY_WORKER_ID": "cross-chapter-worker",
        "NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID": harness.pack_id,
    }
    execution = build_production_execution_composition(
        settings, env=env, chapter_fixture_factory=transport
    )
    chapter = build_chapter_authority_application(
        settings,
        execution=execution,
        env=env,
        runtime_fault_injector=transport.checkpoint,
    )
    from novel_forge.modules.book_followup_authority.application import (
        BookFollowupAuthorityApplication,
    )

    followup = BookFollowupAuthorityApplication(
        DATABASE_URL, application_build_id="cross-chapter-test", commit_sha="e" * 40
    )
    authority = PostgresBookAuthority(
        DATABASE_URL,
        followup_application=followup,
        chapter_port=ChapterAuthorityCommandAdapter(
            chapter, external_effect_adapters=execution.external_effect_adapters
        ),
        application_build_id="cross-chapter-test",
        commit_sha="e" * 40,
        legacy_fixture_input_allowed=True,
    )
    helper = book_support.BookToChapterAuthorityVerticalPostgresTests()
    principal = helper._principal(project)
    worker = Principal(
        principal_id="cross-chapter-worker",
        principal_type=PrincipalType.WORKER,
        permissions=frozenset({"chapter.authority.execute", "external_effect.execute"}),
        project_scope=frozenset({project}),
        authentication_source="integration-test",
    )
    candidates = list(
        chapter_support.PostgreSQLOnlyChapterSliceTests.release_evidence(project)
    )
    plan_transform = prepare_plans(project, harness.workspace_id, candidates) if prepare_plans else None
    plans = helper._seed_two_chapter_plans(
        project, candidates, canonical_execution=True, plan_transform=plan_transform
    )
    versions = helper._seed_book_inputs(project, scope_already_seeded=True)
    profile_id = f"{project}:production-profile:v1"
    profile = {
        "cross_chapter_review_policy": {
            "version": WINDOW_POLICY,
            "source_token_budget": 8000,
        }
    }
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            "INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,'production_profile')",
            [profile_id, project],
        )
        uow.cursor.execute(
            "INSERT INTO authority_asset_version(asset_version_id,asset_id,version_number,lifecycle,eligibility,governance,content,content_hash,schema_version) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,'production-profile.v1')",
            [profile_id, profile_id, Jsonb(profile), digest(profile)],
        )
        uow.commit()
    book = authority.start(
        StartBookProductionCommand(
            project_id=project,
            workspace_id=harness.workspace_id,
            book_id=f"book:{project}",
            actor_id=principal.principal_id,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            stable_idempotency_key=f"{project}:book",
            book_design_version=versions.pop("book_design_version"),
            book_plan_version=versions.pop("book_plan_version"),
            production_profile_version=profile_id,
            longform_context_versions=versions,
            target_chapter_count=2,
            input_mode="LEGACY_FIXTURE_INPUT_MODE",
        ),
        principal=principal,
    )

    def restart():
        fresh_execution = build_production_execution_composition(
            settings, env=env, chapter_fixture_factory=transport
        )
        return build_chapter_authority_application(
            settings,
            execution=fresh_execution,
            env=env,
            runtime_fault_injector=transport.checkpoint,
        )

    return (
        project,
        authority,
        chapter,
        principal,
        worker,
        book,
        candidates,
        plans,
        restart,
    )


@pytest.mark.parametrize("receipt_loss", [False, True])
def test_book_accepted_prose_drives_targeted_repair_and_acceptance(
    tmp_path, receipt_loss
):
    transport = ProseTransport(receipt_loss)
    project, authority, chapter, principal, worker, book, candidates, plans, restart = (
        make_book(tmp_path, transport)
    )
    interrupted_effect = None
    workspaces = []
    for number in (1, 2):
        plan = plans[number]
        command = SubmitBookChapterCommand(
            book_run_id=book.book_run_id,
            chapter_number=number,
            title=f"Chapter {number}",
            premise="A choice has an irreversible cost.",
            chapter_plan_asset_version_id=plan["asset_version_id"],
            chapter_plan_content_hash=plan["content_hash"],
            context_candidates=tuple(
                plan if item["asset_type"] == "chapter_plan" else item
                for item in candidates
            ),
            preparation_report={
                "stage_context_token_budgets": {
                    "review": 64000,
                    "rereview": 64000,
                    "revision": 64000,
                }
            },
        )
        dispatched = authority.submit_chapter(command, principal=principal)
        assert (
            authority.submit_chapter(command, principal=principal)[
                "chapter_root_operation_id"
            ]
            == dispatched["chapter_root_operation_id"]
        )
        for _ in range(len(ChapterNode) * 3):
            try:
                tick = chapter.scheduler(principal=worker).tick(
                    project_id=project,
                    root_operation_id=dispatched["chapter_root_operation_id"],
                )
            except ReceiptCommitLoss:
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute(
                        "SELECT external_effect_id, request_payload, (SELECT receipt_id FROM authority_external_effect_dispatch dispatch WHERE dispatch.external_effect_id=effect.external_effect_id AND receipt_id <> '') FROM authority_external_effect effect WHERE project_id=%s AND capability='model.review' AND status='SUCCEEDED' ORDER BY created_at DESC LIMIT 1",
                        [project],
                    )
                    interrupted_effect = uow.cursor.fetchone()
                    assert interrupted_effect[1]["input"]["cross_chapter_window"][
                        "sources"
                    ]
                    uow.cursor.execute(
                        "SELECT count(*) FROM authority_operation_output_asset output JOIN authority_operation operation USING(operation_id) WHERE operation.project_id=%s AND operation.definition_name='chapter.review.evaluate' AND (operation.command_payload->>'chapter')::int=2 AND output.output_key='chapter.review'",
                        [project],
                    )
                    assert uow.cursor.fetchone() == (0,)
                    uow.cursor.execute(
                        "UPDATE authority_lease_acquisition lease SET expires_at=acquired_at+INTERVAL '1 microsecond' FROM authority_attempt attempt JOIN authority_operation operation USING(operation_id) WHERE lease.attempt_id=attempt.attempt_id AND operation.project_id=%s AND operation.definition_name='chapter.review.evaluate' AND lease.status='HELD'",
                        [project],
                    )
                    uow.commit()
                chapter = restart()
                continue
            if tick.saga_status == "SUCCEEDED":
                break
        assert tick.saga_status == "SUCCEEDED"
        authority.reconcile_chapter(dispatched["chapter_request_id"])
        accepted = authority.accept_chapter(
            dispatched["chapter_request_id"], principal=principal
        )
        assert (
            authority.accept_chapter(
                dispatched["chapter_request_id"], principal=principal
            )
            == accepted
        )
        workspaces.append(
            chapter.query.require_workspace(
                project_id=project,
                root_operation_id=dispatched["chapter_root_operation_id"],
            )
        )
    first = next(
        item
        for item in workspaces[0]["artifacts"]["candidates"]
        if item["asset_type"] == "best_draft_candidate"
    )
    second = next(
        item
        for item in workspaces[1]["artifacts"]["candidates"]
        if item["asset_type"] == "best_draft_candidate"
    )
    assert HISTORY in first["content"]["text"]
    assert (
        REPAIRED in second["content"]["text"]
        and BROKEN not in second["content"]["text"]
    )
    review = next(
        item["content"]
        for item in workspaces[1]["artifacts"]["diagnoses"]
        if item["asset_type"] == "review_report"
    )
    rereview = next(
        item["content"]
        for item in workspaces[1]["artifacts"]["diagnoses"]
        if item["asset_type"] == "re_review_report"
        and item["content"].get("initial_review_version_id")
    )
    assert review["cross_chapter_window"] == rereview["cross_chapter_window"]
    assert (
        review["cross_chapter_window"]["sources"][0]["asset_version_id"]
        == first["asset_version_id"]
    )
    assert rereview["resolved_issue_codes"] == [review["issues"][0]["code"]]
    assert workspaces[1]["cross_chapter_review_enabled"]
    assert workspaces[1]["acceptance"]["accepted_through_chapter"] == 2
    for stage, inputs in transport.calls:
        if stage not in {"review", "rereview"}:
            assert "cross_chapter_window" not in inputs
    snapshot = authority.require_chapter_request(dispatched["chapter_request_id"])[
        "command_payload"
    ]["accepted_prose_snapshot"]
    with pytest.raises(KernelError, match="CROSS_CHAPTER_REVIEW_FRONTIER_STALE"):
        require_frozen_prose_frontier(
            DATABASE_URL,
            snapshot=snapshot,
            project_id=project,
            workspace_id=snapshot["workspace_id"],
            chapter=2,
        )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        assert (
            uow.repositories.asset_documents.require(
                project_id=project, asset_version_id=first["asset_version_id"]
            ).content
            == first["content"]
        )
        uow.cursor.execute(
            "SELECT count(*) FROM authority_book_chapter_acceptance WHERE book_run_id=%s",
            [book.book_run_id],
        )
        assert uow.cursor.fetchone() == (2,)

    review_calls = [inputs for stage, inputs in transport.calls if stage == "review"]
    assert len(review_calls) == 2
    assert bool(interrupted_effect) == receipt_loss
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            "SELECT external_effect_id, request_payload, (SELECT receipt_id FROM authority_external_effect_dispatch dispatch WHERE dispatch.external_effect_id=effect.external_effect_id AND receipt_id <> '') FROM authority_external_effect effect WHERE project_id=%s AND capability='model.review' ORDER BY created_at",
            [project],
        )
        effects = uow.cursor.fetchall()
        assert len(effects) == 2
        effect_id, payload, receipt = effects[-1]
        binding = payload["_production_execution"]["capability_runtime"]
        assert binding["output_schema_ref"].endswith("cross-chapter-v1")
        assert binding["provider_admission"]["total_reserved"] > len(HISTORY.encode())
        from novel_forge.modules.chapter_authority.provider_views import (
            build_provider_task_view,
        )

        admission = uow.repositories.asset_documents.require(
            project_id=project,
            asset_version_id=binding["provider_admission_asset_version_id"],
        ).content["contract"]
        hashes = admission["prompt_materialization"]["provider_view"][
            "component_hashes"
        ]
        assert hashes["provider_task_view"] == digest(
            build_provider_task_view("review", payload["input"])
        )
        changed = deepcopy(payload["input"])
        changed.pop("cross_chapter_window")
        assert hashes["provider_task_view"] != digest(
            build_provider_task_view("review", changed)
        )
        assert (
            payload["input"]["cross_chapter_window"] == review["cross_chapter_window"]
        )
        if receipt_loss:
            assert (effect_id, payload, receipt) == interrupted_effect
        uow.cursor.execute(
            "SELECT count(*) FROM authority_external_effect_dispatch WHERE external_effect_id=%s",
            [effect_id],
        )
        assert uow.cursor.fetchone() == (1,)

        uow.cursor.execute(
            "SELECT count(*) FROM authority_budget_reservation WHERE project_id=%s AND operation_id=(SELECT operation_id FROM authority_external_effect WHERE external_effect_id=%s) AND status='SETTLED'",
            [project, effect_id],
        )
        assert uow.cursor.fetchone() == (1,)


def test_cross_chapter_context_overflow_keeps_candidate_and_creates_no_review_effect(
    tmp_path,
):
    transport = ProseTransport()
    project, authority, chapter, principal, worker, book, candidates, plans, _ = (
        make_book(tmp_path, transport)
    )
    plan = plans[1]
    dispatched = authority.submit_chapter(
        SubmitBookChapterCommand(
            book_run_id=book.book_run_id,
            chapter_number=1,
            title="A bounded review",
            premise="A choice costs a safe exit.",
            chapter_plan_asset_version_id=plan["asset_version_id"],
            chapter_plan_content_hash=plan["content_hash"],
            context_candidates=tuple(
                plan if item["asset_type"] == "chapter_plan" else item
                for item in candidates
            ),
            preparation_report={"stage_context_token_budgets": {"review": 1}},
        ),
        principal=principal,
    )
    with pytest.raises(KernelError, match="CROSS_CHAPTER_REVIEW_CONTEXT_INSUFFICIENT"):
        for _ in range(len(ChapterNode)):
            chapter.scheduler(principal=worker).tick(
                project_id=project,
                root_operation_id=dispatched["chapter_root_operation_id"],
            )
    workspace = chapter.query.require_workspace(
        project_id=project, root_operation_id=dispatched["chapter_root_operation_id"]
    )
    assert len(workspace["artifacts"]["candidates"]) == 1
    assert workspace["artifacts"]["candidates"][0]["asset_type"] == "draft_chapter"
    assert workspace["acceptance"] is None
    assert not [call for call in transport.calls if call[0] == "review"]
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            "SELECT count(*) FROM authority_external_effect WHERE project_id=%s AND capability='model.review'",
            [project],
        )
        assert uow.cursor.fetchone() == (0,)
