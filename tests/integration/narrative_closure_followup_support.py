from dataclasses import replace
import json

import pytest

from novel_forge.api.authority_dependencies import build_production_execution_composition, build_longform_prose_review_model_port
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.book_authority.completion import PostgresBookCompletionAuthority
from novel_forge.modules.book_authority.editorial import BookEditorialWorkflow
from novel_forge.modules.book_followup_authority.application import BookFollowupAuthorityApplication
from novel_forge.modules.book_followup_authority.prose_coordinator import BookProseReviewCoordinator
from novel_forge.modules.book_followup_authority.prose_review import PROSE_DIMENSIONS
from novel_forge.modules.capability_packs.longform_profiles import build_longform_prose_review_pack_profile
from novel_forge.modules.capability_packs.validation_deployment import install_longform_validation_pack, register_validation_runtime_definitions
from novel_forge.modules.story_planning_runtime.application import _command_from_payload
from novel_forge.modules.story_planning_runtime.domain import PlanningGenerationStatus
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.capability_pack_postgres_support import PACK_PERMISSIONS, ROOT


def _metadata(key):
    return {"idempotency_key": "joint-followup:" + key, "trace_id": "joint-followup:" + key, "correlation_id": "joint-followup"}


def _accepted_history(database_url, book_run_id):
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT chapter_number,acceptance_id,chapter_outcome_asset_version_id,story_state_asset_version_id,
            canon_snapshot_asset_version_id FROM authority_book_chapter_acceptance WHERE book_run_id=%s ORDER BY chapter_number""", [book_run_id])
        return uow.cursor.fetchall()


def prepare_next_plan_until_ready(captured):
    composition, run = captured["composition"], captured["source_book_run_id"]
    book = composition.authority.require(run)
    chapter = book["accepted_through_chapter"] + 1
    for _ in range(30):
        with AuthorityUnitOfWork(composition.authority.database_url) as uow:
            uow.cursor.execute("""SELECT binding.asset_version_id,binding.execution_scope FROM active_story_plan_version active
                JOIN story_plan_binding binding USING(binding_id) JOIN authority_asset_version version ON version.asset_version_id=binding.asset_version_id
                WHERE active.project_id=%s AND active.book_id=%s AND binding.contract_type='CHAPTER' AND binding.freshness='CURRENT'
                AND (version.content->>'chapter_number')::int=%s""", [book["project_id"], book["book_id"], chapter])
            row = uow.cursor.fetchone()
        if row:
            assert row[1] == "PLANNED", row
            return row[0]
        tick = composition.tick(run)
        assert str(tick.action) not in {"DISPATCH_CHAPTER", "FREEZE_CHAPTER_PLAN"}, tick
    raise AssertionError("Native supervisor did not prepare a future unfrozen Chapter plan")


def run_joint_followup(captured, *, tmp_path):
    try:
        return _run_joint_followup(captured, tmp_path=tmp_path)
    finally:
        (tmp_path / "followup-world-planning-calls.json").write_text(
            json.dumps(captured["transport"].calls, ensure_ascii=False, indent=2, default=str)
        )


def _run_joint_followup(captured, *, tmp_path):
    composition = captured["composition"]
    database_url = composition.authority.database_url
    book = composition.authority.require(captured["source_book_run_id"])
    assert book["accepted_through_chapter"] == 2
    before = _accepted_history(database_url, book["book_run_id"])

    def metadata(key):
        return _metadata(book["book_run_id"] + ":" + key)
    principal = replace(composition.principal, authentication_source="server_configuration", permissions=composition.principal.permissions | set(PACK_PERMISSIONS) | {
        "book.authority.query", "book.authority.execute", "book.followup:longform.prose_review", "agent.authority.admin"})
    scope = {key: book[key] for key in ("project_id", "workspace_id", "book_run_id")}
    scope["principal"] = principal
    build, sha = composition.authority.application_build_id, composition.authority.commit_sha
    versions = register_validation_runtime_definitions(database_url, application_build_id=build, commit_sha=sha)
    profile = build_longform_prose_review_pack_profile(ROOT, operation_definition_hash=versions["prose_review"], pack_id="joint-prose-" + book["project_id"])
    install_longform_validation_pack(database_url, profile=profile, pack_version="1.0.0", agent_generation=1, expected_activation_version=0,
        project_id=book["project_id"], workspace_id=book["workspace_id"], book_id=book["book_id"], application_build_id=build, commit_sha=sha,
        compiler=replace(principal, principal_id="joint-prose-compiler"), approver=replace(principal, principal_id="joint-prose-approver"),
        agent_admin=principal, agent_domain="book_followup", agent_scope_type="BOOK")
    calls, recheck, primary_relation, counter_ranges = [], [False], [None], [None]

    def transport(stage, inputs):
        assert stage == "longform_prose_review"
        with AuthorityUnitOfWork(database_url) as uow:
            uow.cursor.execute("""SELECT version.content FROM authority_asset asset JOIN authority_asset_version version USING(asset_id)
                WHERE asset.project_id=%s AND asset.asset_type='longform_prose_review_window'
                AND version.content->>'manifest_digest'=%s AND version.content->'window'->>'window_id'=%s""",
                [book["project_id"], inputs["manifest_digest"], inputs["window_id"]])
            source = uow.cursor.fetchone()[0]
        window = source["window"]
        findings = []
        if window.get("relation_hypothesis") and primary_relation[0] is None:
            primary_relation[0] = window["window_id"]
        coordinates = {(span["asset_version_id"], span["start"], span["end"]) for span in window["spans"]}
        if window["window_id"] == primary_relation[0] or (recheck[0] and coordinates == counter_ranges[0]):
            evidence = [{"asset_version_id": span["asset_version_id"], "text_hash": span["text_hash"], "start": span["start"],
                "end": span["end"], "quote": span["text"]} for span in window["spans"]]
            findings.append({"lineage_id": "joint-promise-repetition", "dimension": "motivation_cost", "judgment": "INTENTIONAL" if recheck[0] else "ISSUE",
                "severity": "NONE" if recheck[0] else "MAJOR", "confidence": 0.6,
                "claim": "承诺再次出现可能只是重复，需核对新的行动代价。", "rationale": "scripted复核：证词送达与护送证人是不同步骤；重复承诺有明确未完成对象。" if recheck[0] else "scripted误报用于验证定位反证恢复，不代表实际文学评价。", "evidence": evidence})
            if not recheck[0]:
                findings.append({"lineage_id": "joint-promise-future-check", "dimension": "setup_progress_payoff", "judgment": "INSUFFICIENT_EVIDENCE", "severity": "NONE", "confidence": 0.6,
                    "claim": "证词已送达，护送证人仍未完成；下一步需要确认位置与证灯余油。", "rationale": "当前稿没有兑现人员安全，未来计划不能将两项承诺混为已完成事实。", "evidence": evidence})
        result = {"schema_version": "longform-prose-review.v1", "manifest_digest": source["manifest_digest"], "window_id": window["window_id"],
            "reviewed_dimensions": list(PROSE_DIMENSIONS), "findings": findings}
        calls.append({"stage": stage, "window_id": window["window_id"], "result": result})
        return result

    settings = IndustrialSettings(root=ROOT, environment="development", storage_authority="postgresql", database_url=database_url)
    env = {"NOVEL_FORGE_ENVIRONMENT": "development", "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2", "NOVEL_FORGE_COMMIT_SHA": sha,
        "NOVEL_FORGE_APPLICATION_BUILD_ID": build, "NOVEL_FORGE_LONGFORM_PROSE_REVIEW_CAPABILITY_PACK_ID": profile.pack_id,
        "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(tmp_path / "joint-prose-objects")}
    execution = build_production_execution_composition(settings, env=env, chapter_fixture_factory=transport)
    execution.gateway.routes = {stage: replace(route, model_context_limit=200000) for stage, route in execution.gateway.routes.items()}
    model = build_longform_prose_review_model_port(settings, execution=execution, env=env)
    model.capability_binder.pack_environment = model.capability_binder.pack_runtime_profile = "validation"
    followup = BookFollowupAuthorityApplication(database_url, application_build_id=build, commit_sha=sha, prose_model_port=model)
    coordinator = BookProseReviewCoordinator(followup)
    policy = {"policy_version": "joint-prose-v1", "window_codepoints": 1024, "overlap_codepoints": 64, "context_token_budget": 16000,
        "maximum_windows": 12, "execution_mode": "AUTOMATIC", "follow_acceptance": True, "relation_window_limit": 2, "relation_retrieval_version": "accepted-state-relations.v2"}
    run = coordinator.start(**scope, **metadata("start-accepted-state-v2"), policy=policy)

    def finish(run_id):
        for _ in range(15):
            progress = coordinator.report(**scope, run_id=run_id)
            if progress["review_complete"]:
                return progress
            tick = coordinator.automatic_tick(**scope, run_id=run_id)
            assert tick.get("status") not in {"BLOCKED", "BUDGET_PAUSED"}, tick
        raise AssertionError("Native automatic prose review exceeded its explicit bound")

    progress = finish(run["run_id"])
    remote = [window for window in progress["manifest"]["windows"] if window.get("relation_hypothesis")]
    assert remote, "Actual accepted manuscript must produce an automatic cross-window hypothesis"
    future = next(item for item in progress["findings"] if item["lineage_id"] == "joint-promise-future-check")
    report = next(item for item in progress["operations"] if item["window_id"] == future["members"][0]["window_id"])
    target = prepare_next_plan_until_ready(captured)
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT operation.command_payload->'payload' FROM authority_story_planning_generation generation
            JOIN authority_operation operation ON operation.operation_id=generation.operation_id
            WHERE generation.project_id=%s AND generation.candidate_asset_version_id=%s""", [book["project_id"], target])
        payload = uow.cursor.fetchone()[0]
    command = replace(_command_from_payload(payload), change_evidence_version_ids=(report["report_asset_version_id"],),
        repair_of_candidate_id="", repair_of_operation_id="", repair_result_asset_version_id="",
        repair_result_diagnostic=None, repair_reason="", repair_number=0, runtime_continuation_id="",
        idempotency_key="joint-followup:" + book["book_run_id"] + ":replacement-v2", trace_id="joint-followup:replacement", correlation_id=run["run_id"], auto_approve_low_risk=False)
    from novel_forge.modules.book_followup_authority.prose_change_evidence import require_prose_planning_evidence
    from novel_forge.modules.command_kernel.errors import KernelError
    for invalid_command, invalid_sha, expected in (
        (replace(command, execution_contract_version="1.15.0"), sha, "PLANNING_PROSE_EVIDENCE_INVALID"),
        (command, "0" * 40, "PLANNING_PROSE_EVIDENCE_INVALID"),
        (replace(command, edition_execution={}, world_preparation_request={**command.world_preparation_request, "book_run_id": "different-edition-run"}), sha,
            "PLANNING_PROSE_EDITION_SCOPE_INVALID"),
        (replace(command, edition_execution={}, world_preparation_request=None), sha, "PLANNING_PROSE_EDITION_SCOPE_INVALID"),
    ):
        with pytest.raises(KernelError, match=expected):
            require_prose_planning_evidence(database_url, command=invalid_command,
                asset_version_id=report["report_asset_version_id"], commit_sha=invalid_sha)
    with pytest.raises(KernelError, match="PLANNING_PROSE_EVIDENCE_INVALID"):
        require_prose_planning_evidence(database_url, command=command, asset_version_id=target, commit_sha=sha)
    captured["transport"].joint_future_review = True
    try:
        generated = composition.planning.generate(command, principal=principal)
    finally:
        captured["transport"].joint_future_review = False
    assert generated.status is PlanningGenerationStatus.APPROVAL_PENDING, generated
    arguments = dict(**scope, run_id=run["run_id"], expected_version=progress["expected_version"], lineage_id=future["lineage_id"], finding_digest=future["finding_digest"],
        target_asset_version_id=target, proposed_asset_version_id=generated.candidate_asset_version_id,
        rationale="scripted授权处置：仅未来第三章核对未完成承诺；保留前两章事实、人物秘密和已接纳阶段。", **metadata("proposal"))
    preview = coordinator.impact_preview(plan_change=composition.plan_change, **arguments)
    assert preview["proposal_created"] is False
    proposed = coordinator.propose_plan_change(plan_change=composition.plan_change, **arguments)
    proposal = proposed["proposal"]
    dispositions = [{"hypothesis_id": item["hypothesis_id"], "disposition": "DEFER", "evidence": [],
        "rationale": "尚无足够证据判定此检索关联为语义依赖或误报；保留待核验假设，不创建推测性的历史或其他计划变更。"}
        for item in proposal["semantic_impact_discovery"]["hypotheses"]]
    composition.plan_change.decide(proposal["proposal_id"], approved=True, authority_type="PLAN_CHANGE_AUTHORITY", authority_version="joint-scripted-review-v1",
        evidence={"semantic_impact_dispositions": dispositions, "review_run_id": run["run_id"], "future_only": True, "accepted_through_chapter": 2}, principal=principal)
    activated = composition.plan_change.activate(proposal["proposal_id"], principal=principal)
    assert activated["status"] == "ACTIVE"
    assert _accepted_history(database_url, book["book_run_id"]) == before
    recheck[0] = True
    counter_ranges[0] = {(span["asset_version_id"], span["start"], span["end"]) for span in remote[0]["spans"]}
    review_ranges = [{key: span[key] for key in ("asset_version_id", "start", "end")} for span in remote[0]["spans"]]
    checked_run = coordinator.start(**scope, **metadata("recheck"), policy=policy, evidence_ranges=review_ranges)
    checked = finish(checked_run["run_id"])
    false_alarm = next(item for item in checked["findings"] if item["lineage_id"] == "joint-promise-repetition")
    completion = PostgresBookCompletionAuthority(database_url, application_build_id=build, commit_sha=sha)
    BookEditorialWorkflow(completion).record(**scope, expected_version=0, kind="POLICY", content={"policy": {"policy_version": "joint-scripted-review-v1", "enabled": True,
        "authorized_reviewers": [principal.principal_id], "minimum_signatures": 1, "allow_minor_exceptions": False},
        "approval_rationale": "scripted具名操作者协议验证，不是真人文学评价或发布授权。"}, **metadata("reviewer-policy"))
    counter_window = next(window for window in checked["manifest"]["windows"]
        if not window.get("relation_hypothesis") and {(span["asset_version_id"], span["start"], span["end"]) for span in window["spans"]} == counter_ranges[0])
    counter = next(item for item in checked["operations"] if item["window_id"] == counter_window["window_id"] and not item.get("source_run_id"))
    disposition = coordinator.disposition(**scope, run_id=checked_run["run_id"], expected_version=checked["expected_version"], lineage_id=false_alarm["lineage_id"], finding_digest=false_alarm["finding_digest"],
        decision="DISMISSED_WITH_EVIDENCE", rationale="scripted反证覆盖全部原文位置：同一承诺的继续有未完成对象。", consumer_asset_version_id=counter["report_asset_version_id"], **metadata("dismiss"))
    assert disposition["resolution_evidence"]["resolution"] == "DISMISSED_BY_AUTHORIZED_REVIEWER"
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT operation_id,status FROM authority_external_effect WHERE operation_id=ANY(%s)", [[item["operation_id"] for item in checked["operations"]]])
        effects = uow.cursor.fetchall()
    assert effects and all(status == "SUCCEEDED" for _, status in effects)
    result = {"review_run_id": run["run_id"], "review": progress, "preview": preview, "plan_change": activated,
        "counter_review": checked, "counter_disposition": disposition, "accepted_history": before, "effects": effects, "calls": calls,
        "evidence_ceiling": "SCRIPTED_NATIVE_ENGINEERING_NOT_REAL_PROVIDER_OR_HUMAN_QUALITY"}
    (tmp_path / "joint-followup.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return result
