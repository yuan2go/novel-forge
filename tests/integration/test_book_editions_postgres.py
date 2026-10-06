from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from novel_forge.modules.authority_security import PrincipalType
from novel_forge.modules.book_authority.edition_application import BookEditionApplication
from novel_forge.modules.book_authority.edition_runtime import edition_dispatch_binding
from novel_forge.modules.chapter_authority.realization_composition import serialize_realization
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.workers.book_authority import execute_book_coordination_claim, schedule_book_coordination_jobs
from tests.integration import test_core_functional_loops_postgres as core
from tests.integration import test_world_actor_isolation_postgres as actors
from tests.integration import world_causal_production_support as world
from tests.integration.screenplay_production_support import run_screenplay_vertical


def persistent_actor_book(request, monkeypatch, tmp_path, *, joint_story=False):
    captured = {}
    execute = world.execute_autonomous_world_vertical
    temporary = core.tempfile.TemporaryDirectory

    def keep_objects(*args, **kwargs):
        if kwargs.get("prefix") == "narrative-evolution-opening-":
            path = tmp_path / "native-object-store"
            path.mkdir()
            return nullcontext(str(path))
        return temporary(*args, **kwargs)

    def capture(**kwargs):
        captured.update(kwargs)
        result = execute(**kwargs)
        captured["source_book_run_id"] = result["book_run_id"]
        return result

    monkeypatch.setattr(core.tempfile, "TemporaryDirectory", keep_objects)
    monkeypatch.setattr(world, "execute_autonomous_world_vertical", capture)
    options = {}
    if joint_story:
        from tests.integration.narrative_closure_joint_support import STORY, JointStoryTransport, approve_joint_craft
        options = {"story": STORY, "transport_mixin": JointStoryTransport, "seed_hook": approve_joint_craft}
    actors.run_actor_receipt_recovery(request, monkeypatch, persistent_intents=True, **options)
    return captured


def advance_to(captured, book_run_id, target, *, defer_on_dispatch=False):
    composition = captured["composition"]
    worker = replace(composition.principal, principal_id="edition-native-worker", principal_type=PrincipalType.WORKER,
                     permissions=composition.principal.permissions - {"book.authority.approve_replan"})
    jobs = RuntimeJobAuthority(composition.authority.database_url)
    actions = []
    for _ in range(60):
        book = composition.authority.require(book_run_id)
        if book["accepted_through_chapter"] == target:
            return actions
        schedule_book_coordination_jobs(composition.query, jobs, limit=1, book_run_id=book_run_id)
        claim = jobs.claim(runtime_group="book", worker_id=worker.principal_id, lease_seconds=30,
                           job_kinds=("BOOK_COORDINATION_TICK",), subject_kind="BOOK_RUN", subject_id=book_run_id)
        assert claim is not None, book
        result = execute_book_coordination_claim(jobs, composition, claim)
        jobs.complete(claim, result)
        actions.append(result)
        if result["action"] == "DISPATCH_CHAPTER":
            if defer_on_dispatch:
                return actions
            scheduler = captured["chapter_application"].scheduler(principal=worker)
            for _ in range(50):
                tick = scheduler.tick(project_id=book["project_id"], root_operation_id=result["operation_id"])
                if tick.saga_status == "SUCCEEDED":
                    break
            else:
                raise AssertionError("Edition validation Chapter did not finish through its native graph")
    raise AssertionError(f"Edition validation did not reach {target}: {actions}")


def test_edition_candidate_uses_native_acceptance_and_isolates_source_facts(request, monkeypatch, tmp_path):
    captured = persistent_actor_book(request, monkeypatch, tmp_path, joint_story=os.environ.get("NOVEL_FORGE_EDITION_JOINT_STORY") == "1")
    composition = captured["composition"]
    joint_followup = None
    if os.environ.get("NOVEL_FORGE_EDITION_JOINT_STORY") == "1":
        from tests.integration.narrative_closure_followup_support import run_joint_followup
        joint_followup = run_joint_followup(captured, tmp_path=tmp_path)
    principal = replace(composition.principal, permissions=composition.principal.permissions | {"book.authority.query"})
    source_run = captured["source_book_run_id"]
    book = composition.authority.require(source_run)
    app = BookEditionApplication(composition.authority.database_url, application_build_id=composition.authority.application_build_id,
                                 commit_sha=composition.authority.commit_sha)
    scope = dict(project_id=book["project_id"], workspace_id=book["workspace_id"], book_run_id=source_run, principal=principal)
    manifest = app.query(**scope)["source_manifest"]
    original = app.execute(action="create", **scope, data={"base_manifest_digest": manifest["manifest_digest"]}, idempotency_key=f"edition:{source_run}:origin")
    assert app.execute(action="create", **scope, data={"base_manifest_digest": manifest["manifest_digest"]}, idempotency_key=f"edition:{source_run}:origin") == {**original, "replayed": True}
    original_screenplay = run_screenplay_vertical(composition.authority.database_url, book, original["revision_id"], principal, tmp_path,
        application_build_id=app.application_build_id, commit_sha=app.commit_sha, run_samples=False)
    old_inflight = advance_to(captured, source_run, 3, defer_on_dispatch=True)
    assert old_inflight[-1]["action"] == "DISPATCH_CHAPTER"
    candidate = app.execute(action="create", **scope, data={"base_revision_id": original["revision_id"], "base_manifest_digest": manifest["manifest_digest"]},
                            idempotency_key=f"edition:{source_run}:candidate")
    units = deepcopy(manifest["units"])
    units[1]["scene_artifacts"][0]["text"] += " 风声掠过檐角，话音却很稳。"
    units[1]["text"] = serialize_realization(units[1]["scene_artifacts"], units[1].get("scene_separators"))
    save_data = {"revision_id": candidate["revision_id"], "expected_version": candidate["version"], "base_manifest_digest": candidate["manifest_digest"],
                 "units": units, "reason": "作者修订第二章收束句，保留承诺与证词因果", "change_kind": "EXPRESSION"}
    saved = app.execute(action="save", **scope, data=save_data, idempotency_key=f"edition:{source_run}:save")
    assert app.execute(action="save", **scope, data=save_data, idempotency_key=f"edition:{source_run}:save") == {**saved, "replayed": True}
    with pytest.raises(KernelError, match="EDITION_VERSION_CONFLICT"):
        app.execute(action="save", **scope, data=save_data, idempotency_key=f"edition:{source_run}:stale-save")
    with AuthorityUnitOfWork(composition.authority.database_url) as uow:
        for receipt, expected in ((original, {source["asset_version_id"] for source in manifest["sources"]}),
                                  (candidate, {original["revision_id"]}), (saved, {candidate["revision_id"]})):
            uow.cursor.execute("SELECT input_asset_snapshot FROM authority_operation WHERE operation_id=%s", [receipt["operation_id"]])
            frozen = uow.cursor.fetchone()[0]
            assert expected <= {item["asset_version_id"] for item in frozen}
            assert all(item["content_hash"].startswith("sha256:") for item in frozen)
    rejected = app.execute(action="create", **scope, data={"base_revision_id": original["revision_id"], "base_manifest_digest": manifest["manifest_digest"]},
                           idempotency_key=f"edition:{source_run}:rejected-candidate")
    app.execute(action="reject", **scope, data={"revision_id": rejected["revision_id"], "expected_version": rejected["version"], "reason": "作者保留历史并弃用该候选"},
                idempotency_key=f"edition:{source_run}:reject-candidate")
    with pytest.raises(KernelError, match="EDITION_VALIDATION_REJECTED"):
        app.start_validation(authority=composition.authority, **scope, revision_id=rejected["revision_id"])
    with AuthorityUnitOfWork(composition.authority.database_url) as uow:
        uow.cursor.execute("SELECT count(*) FROM authority_book_edition_run WHERE revision_id=%s", [rejected["revision_id"]])
        assert uow.cursor.fetchone()[0] == 0
    with pytest.raises(KernelError, match="EDITION_SELECTED_REVISION_IMMUTABLE"):
        app.execute(action="reject", **scope, data={"revision_id": original["revision_id"], "expected_version": original["version"], "reason": "正式稿不得用候选拒绝动作撤销"},
                    idempotency_key=f"edition:{source_run}:reject-selected")
    with pytest.raises(KernelError, match="EDITION_NOT_ADMITTED"):
        app.execute(action="select", **scope, data={"revision_id": saved["revision_id"], "expected_head_version": 1, "reason": "未审稿禁止切换"}, idempotency_key=f"edition:{source_run}:premature-selection")
    queried = app.query(**scope, revision_id=saved["revision_id"])
    with pytest.raises(KernelError, match="EDITION_FORMAL_EXPORT_REQUIRES_SELECTION"):
        app.export_manuscript(**scope, revision_id=saved["revision_id"])
    candidate_export = app.export_manuscript(**scope, revision_id=saved["revision_id"], export_kind="CANDIDATE")
    assert candidate_export["export"]["kind"] == "CANDIDATE"
    formal_export = app.export_manuscript(**scope, revision_id=original["revision_id"])
    assert formal_export["revision"]["manifest"] == manifest
    assert formal_export["export"]["manifest_digest"] == manifest["manifest_digest"]
    assert queried["head"]["selected_revision_id"] == original["revision_id"]
    assert queried["diff"]["changes"]
    assert app.query(**scope, revision_id=original["revision_id"])["revision"]["manifest"] == manifest
    with AuthorityUnitOfWork(composition.authority.database_url) as uow:
        uow.cursor.execute("SELECT acceptance_id,chapter_outcome_asset_version_id,story_state_asset_version_id,canon_snapshot_asset_version_id FROM authority_book_chapter_acceptance WHERE book_run_id=%s ORDER BY chapter_number", [source_run])
        source_acceptances = uow.cursor.fetchall()
    admitted = app.start_validation(authority=composition.authority, **scope, revision_id=saved["revision_id"])
    assert app.start_validation(authority=composition.authority, **scope, revision_id=saved["revision_id"])["validation_book_run_id"] == admitted["validation_book_run_id"]
    validation_run = admitted["validation_book_run_id"]
    assert validation_run != source_run
    assert composition.authority.require(validation_run)["accepted_through_chapter"] == 1
    assert composition.authority.require(validation_run)["current_chapter"] == 1
    inherited = app.query(**scope, revision_id=saved["revision_id"])["bound_runs"][0]["inherited_prefix"]
    assert inherited["through_chapter"] == 1
    assert inherited["accepted_sources"][0]["acceptance_id"] == source_acceptances[0][0]
    with AuthorityUnitOfWork(composition.authority.database_url) as uow:
        uow.cursor.execute("SELECT count(*) FROM authority_book_chapter_acceptance WHERE book_run_id=%s", [validation_run])
        assert uow.cursor.fetchone()[0] == 0
    actions = advance_to(captured, validation_run, 2)
    with pytest.raises(KernelError, match="EDITION_VALIDATION_INCOMPLETE"):
        app.execute(action="validate", **scope, data={"revision_id": saved["revision_id"], "expected_version": saved["version"],
                                                     "validation_book_run_id": validation_run}, idempotency_key=f"edition:{source_run}:validate-submitted")
    inspected = app.query(**scope, revision_id=saved["revision_id"])["validation_result"]
    assert inspected["diff"]["changes"]
    capture_data = {"source_validation_revision_id": saved["revision_id"], "validation_book_run_id": validation_run,
                    "expected_version": saved["version"], "base_manifest_digest": inspected["manifest"]["manifest_digest"],
                    "reason": "保留作者原候选，显式保存原生审改后已接纳正文供版本选择"}
    validated = app.execute(action="create", **scope, data=capture_data, idempotency_key=f"edition:{source_run}:capture-reviewed")
    assert app.execute(action="create", **scope, data=capture_data, idempotency_key=f"edition:{source_run}:capture-reviewed") == {**validated, "replayed": True}
    assert validated["revision_id"] != saved["revision_id"]
    assert validated["source_validation_revision_id"] == saved["revision_id"]
    assert app.query(**scope, revision_id=saved["revision_id"])["revision"]["manifest"] == queried["revision"]["manifest"]
    assert len(validated["accepted_units"]) == 2
    assert validated["accepted_units"][0]["acceptance_id"] == source_acceptances[0][0]
    assert validated["accepted_units"][1]["acceptance_id"] != source_acceptances[1][0]
    selected = app.execute(action="select", **scope, data={"revision_id": validated["revision_id"], "expected_head_version": 1,
                                                           "reason": "已重验正文与事实，切换至显式保存的审改稿"}, idempotency_key=f"edition:{source_run}:select")
    assert selected["continuation_book_run_id"] == validation_run and selected["publication_authorized"] is False
    from novel_forge.modules.chapter_quality_authority.accepted_projection import load_accepted_quality_observations
    def quality_sources(run_id, through):
        return [item["acceptance_id"] for item in load_accepted_quality_observations(composition.authority.database_url,
            project_id=book["project_id"], book_id=book["book_id"], book_run_id=run_id, accepted_through_chapter=through)]
    assert quality_sources(source_run, 2) == [row[0] for row in source_acceptances]
    validation_acceptance_ids = [proof["acceptance_id"] for proof in validated["accepted_units"]]
    assert quality_sources(validation_run, 2) == validation_acceptance_ids
    from novel_forge.modules.book_authority.edition_planning import edition_plan_scope, validate_edition_plan_scope
    assert edition_plan_scope(composition.authority.database_url, book=composition.authority.require(validation_run),
        chapter=3, generator="chapter_plan.generate")["revision_id"] == validated["revision_id"]
    with AuthorityUnitOfWork(composition.authority.database_url) as uow:
        uow.cursor.execute("SELECT command_payload->>'execution_chapter_plan_asset_version_id' FROM authority_book_chapter_request WHERE book_run_id=%s AND chapter_number=2", [validation_run])
        frozen_plan = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=uow.cursor.fetchone()[0])
    frozen_scope = frozen_plan.content["constraint_envelope"]["edition_execution"]
    assert frozen_scope["revision_id"] == saved["revision_id"]
    assert validate_edition_plan_scope(composition.authority.database_url, project_id=book["project_id"], book_id=book["book_id"], scope=frozen_scope)
    with pytest.raises(KernelError, match="EDITION_RUN_NOT_SELECTED"):
        edition_dispatch_binding(composition.authority.database_url, book=composition.authority.require(source_run), chapter=3)
    with AuthorityUnitOfWork(composition.authority.database_url) as uow:
        uow.cursor.execute("SELECT acceptance_id,chapter_outcome_asset_version_id,story_state_asset_version_id,canon_snapshot_asset_version_id FROM authority_book_chapter_acceptance WHERE book_run_id=%s ORDER BY chapter_number", [source_run])
        assert uow.cursor.fetchall() == source_acceptances
        uow.cursor.execute("SELECT book_run_id,count(*) FROM authority_book_narrative_projection_set WHERE project_id=%s GROUP BY book_run_id", [book["project_id"]])
        assert dict(uow.cursor.fetchall()) == {source_run: 2, validation_run: 1}
    old_worker = replace(principal, principal_id="edition-old-frozen-worker", principal_type=PrincipalType.WORKER,
                         permissions=principal.permissions - {"book.authority.approve_replan"})
    scheduler = captured["chapter_application"].scheduler(principal=old_worker)
    unknown_evidence = None
    if os.environ.get("NOVEL_FORGE_EDITION_JOINT_STORY") == "1":
        from tests.integration.narrative_closure_joint_support import settle_joint_unknown
        unknown_evidence = settle_joint_unknown(captured, scheduler=scheduler, project_id=book["project_id"], root_operation_id=old_inflight[-1]["operation_id"])
    else:
        for _ in range(50):
            tick = scheduler.tick(project_id=book["project_id"], root_operation_id=old_inflight[-1]["operation_id"])
            if tick.saga_status == "SUCCEEDED":
                break
        else:
            raise AssertionError("Original frozen Chapter failed to settle after edition switch")
    old_settlement = advance_to(captured, source_run, 3)
    assert composition.authority.require(validation_run)["accepted_through_chapter"] == 2
    assert quality_sources(validation_run, 2) == validation_acceptance_ids
    with AuthorityUnitOfWork(composition.authority.database_url) as uow:
        uow.cursor.execute("SELECT acceptance_id FROM authority_book_chapter_acceptance WHERE book_run_id=%s ORDER BY chapter_number", [source_run])
        settled = [row[0] for row in uow.cursor.fetchall()]
        assert settled[:2] == [row[0] for row in source_acceptances] and len(settled) == 3
    continuation = advance_to(captured, validation_run, 3)
    with AuthorityUnitOfWork(composition.authority.database_url) as uow:
        uow.cursor.execute("SELECT command_payload FROM authority_book_chapter_request WHERE book_run_id=%s AND chapter_number=3", [validation_run])
        continued_command = uow.cursor.fetchone()[0]
        continued_plan = uow.repositories.asset_documents.require(project_id=book["project_id"], asset_version_id=continued_command["execution_chapter_plan_asset_version_id"])
    assert continued_command["preparation_report"]["book_edition"]["revision_id"] == validated["revision_id"]
    assert continued_plan.content["constraint_envelope"]["edition_execution"]["revision_id"] == validated["revision_id"]
    from novel_forge.modules.production_preparation.resolver import PostgresProductionAssetResolver
    resolver = PostgresProductionAssetResolver(composition.authority.database_url)
    assert resolver.resolve_latest(project_id=book["project_id"], asset_type="story_state_snapshot").content["accepted_through_chapter"] == 2
    with pytest.raises(KernelError, match="EDITION_ACCEPTANCE_BOUNDARY_EXCEEDED"):
        resolver.resolve_accepted_for_boundary(project_id=book["project_id"], book_id=book["book_id"],
            asset_type="story_state_snapshot", accepted_chapter=3)
    with pytest.raises(KernelError, match="EDITION_ACCEPTANCE_BOUNDARY_EXCEEDED"):
        load_accepted_quality_observations(composition.authority.database_url, project_id=book["project_id"], book_id=book["book_id"], accepted_through_chapter=3)
    assert len(quality_sources(validation_run, 3)) == 3
    assert resolver.resolve_accepted_for_boundary(project_id=book["project_id"], book_id=book["book_id"],
        asset_type="story_state_snapshot", accepted_chapter=3, book_run_id=validation_run)[0].content["accepted_through_chapter"] == 3
    next_scope = {**scope, "book_run_id": validation_run}
    extended_manifest = app.query(**next_scope)["source_manifest"]
    assert len(extended_manifest["units"]) == 3
    assert len(app.query(**scope, revision_id=saved["revision_id"])["revision"]["manifest"]["units"]) == 2
    snapshot = app.execute(action="create", **next_scope, data={"base_manifest_digest": extended_manifest["manifest_digest"]}, idempotency_key=f"edition:{source_run}:accepted-extension")
    app.execute(action="select", **next_scope, data={"revision_id": snapshot["revision_id"], "expected_head_version": selected["head_version"],
                                                    "reason": "冻结所选稿件后续新增的接纳章节"}, idempotency_key=f"edition:{source_run}:select-extension")
    updated_screenplay = run_screenplay_vertical(composition.authority.database_url, composition.authority.require(validation_run), validated["revision_id"], principal, tmp_path,
        application_build_id=app.application_build_id, commit_sha=app.commit_sha, predecessor_source_id=original_screenplay["source_asset_version_id"], run_samples=os.environ.get("NOVEL_FORGE_EDITION_RUN_SAMPLES") == "1")
    joint_accepted_evidence = None
    if os.environ.get("NOVEL_FORGE_EDITION_JOINT_STORY") == "1":
        from tests.integration.edition_joint_evidence_support import require_joint_accepted_evidence
        joint_accepted_evidence = require_joint_accepted_evidence(captured, source_run=source_run, validation_run=validation_run, tmp_path=tmp_path)
    evidence = {"project_id": book["project_id"], "workspace_id": book["workspace_id"], "book_id": book["book_id"],
                "source_book_run_id": source_run, "validation_book_run_id": validation_run,
                "joint_followup": joint_followup, "joint_accepted_evidence": joint_accepted_evidence, "original": original, "candidate": saved, "reviewed_diff": inspected["diff"], "native_actions": actions, "validation": validated, "selection": selected,
                "continuation": continuation, "extended_snapshot": snapshot,
                "original_screenplay": original_screenplay, "updated_screenplay": updated_screenplay,
                "old_inflight": old_inflight, "old_settlement": old_settlement, "unknown_effect": unknown_evidence,
                "proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY", "actual_real_model_calls": 0}
    request.node.user_properties.append(("book_edition_vertical", json.dumps(evidence, ensure_ascii=False, default=str)))
    Path(tmp_path / "edition-native.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str))
    if output := os.environ.get("NOVEL_FORGE_EDITION_EVIDENCE_PATH"):
        Path(output).write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str))
