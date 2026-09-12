from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import time

from fastapi.testclient import TestClient

from novel_forge.modules.authority_security import PrincipalType
from novel_forge.modules.chapter_authority.execution_gateway import default_chapter_fixture_response
from novel_forge.modules.content_authority import ContentAuthorityApplication, ContentOperationRequest
from novel_forge.modules.content_authority.codecs import CONTENT_CODECS
from novel_forge.modules.story_planning_runtime.execution import planning_fixture_response
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from scripts.run_world_production_smoke import drive, start_command


class OperatorPlanChangeTransport:
    def __init__(self):
        self.calls = []

    def post_provider_checkpoint(self, _point):
        return None

    def planning(self, stage, inputs):
        self.calls.append({"stage": stage, "inputs": inputs})
        if stage == "world_candidates.generate":
            return {"disposition": "NO_OP", "reason": "No separate world action is proposed in the operator-plan protocol fixture.", "candidates": []}
        if stage == "world_candidates.evaluate":
            return {"evaluations": []}
        return planning_fixture_response(stage, inputs)

    def __call__(self, stage, inputs):
        self.calls.append({"stage": stage, "inputs": inputs})
        return default_chapter_fixture_response(stage, inputs)


def execute_operator_plan_change_vertical(*, composition, chapter, snapshot, settings, authority_api):
    principal = composition.principal
    project_id, workspace_id, book_id = snapshot.project_id, snapshot.workspace_id, snapshot.book_id
    authority = composition.authority
    database_url = authority.database_url
    admission = authority.start(start_command(snapshot, actor=principal.principal_id, run_key=f"{project_id}:operator-plan-book", chapters=6), principal=principal)
    book_run_id = admission.book_run_id
    worker = replace(principal, principal_id=f"{project_id}:operator-plan-worker", principal_type=PrincipalType.WORKER,
                     permissions=principal.permissions - {"book.authority.approve_replan"})
    records = []
    checkpoint = drive(composition=composition, chapter=chapter, book_run_id=book_run_id, worker=worker,
                       events=records.append, maximum_ticks=180, deadline=time.monotonic() + 480, stop_after_chapter=3)
    assert checkpoint == "FUTURE_PLAN_CHANGE_REQUIRED", {"reason": checkpoint, "events": records[-5:]}
    assert authority.require(book_run_id)["accepted_through_chapter"] == 3
    target = composition.query.active_plan_covering_chapter(project_id=project_id, book_id=book_id, contract_type="CHAPTER_GROUP", chapter_number=4)
    target_id = target["asset_version_id"]
    assert target["content"]["chapter_range"] == [4, 6]
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT chapter_number,chapter_outcome_asset_version_id,story_state_asset_version_id,canon_snapshot_asset_version_id FROM authority_book_chapter_acceptance WHERE book_run_id=%s ORDER BY chapter_number", [book_run_id])
        accepted_history = uow.cursor.fetchall()
        assert len(accepted_history) == 3
        uow.cursor.execute("SELECT COUNT(*) FROM authority_book_chapter_request WHERE book_run_id=%s AND chapter_number>3", [book_run_id])
        assert uow.cursor.fetchone() == (0,)
    trusted = SimpleNamespace(resolve_api_principal=lambda **_values: replace(principal, permissions=principal.permissions | {"book.authority.query"}),
                              resolve_narrative_evaluator_principal=lambda: principal)

    def post(path, body):
        with patch("novel_forge.api.routers.book_authority.build_trusted_principal_resolver", return_value=trusted), TestClient(authority_api) as client:
            response = client.post(path, json=body)
        assert response.status_code == 200, response.text
        return response.json()

    content = ContentAuthorityApplication(database_url, application_build_id="operator-plan-fixture", commit_sha="e" * 40, integration_proven=CONTENT_CODECS)
    directive = "After chapter 3, change the rescue route while preserving the water cost and accepted history."
    feedback = content.execute(ContentOperationRequest(
        definition_name="planning.change_request.author", project_id=project_id, workspace_id=workspace_id,
        actor_id=principal.principal_id, trace_id=f"{project_id}:operator-change", correlation_id=book_run_id,
        idempotency_key=f"{project_id}:operator-change", payload={"content": {
            "book_id": book_id, "target_plan_version_id": target_id, "directive": directive,
            "preserved_invariants": ["Keep chapters 1–3 accepted history and water cost"],
            "affected_scope": "CHAPTER_GROUP", "accepted_through_chapter": 3,
            "safe_summary": directive, "structured_facts": [],
        }}, input_assets=()), principal=replace(principal, permissions=principal.permissions | {"content.authority.execute", "content.operation:planning.change_request.author"}))
    with patch("novel_forge.api.routers.book_authority.build_trusted_principal_resolver", return_value=trusted), TestClient(authority_api) as client:
        frozen = client.get(f"/product/production/book-authority/books/{book_id}/planning-candidates/{target_id}", params={"project_id": project_id})
    assert frozen.status_code == 200, frozen.text
    command = frozen.json()["frozen_command"]
    command.update(idempotency_key=f"{project_id}:operator-replacement", change_evidence_version_ids=[feedback.asset_version_id],
                   narrative_search_id="", narrative_search_branch_key="", narrative_search_parent_state_asset_version_id="",
                   narrative_search_accepted_through_chapter=0, narrative_search_strategy_directive="",
                   narrative_search_planning_horizon={}, narrative_search_desired_transformation={}, narrative_search_hard_constraints=[])
    generated = post(f"/product/production/book-authority/books/{book_id}/planning-generations", command)
    candidate_id = generated["candidate_asset_version_id"]
    assert generated["status"] == "APPROVAL_PENDING"
    proposal = post(f"/product/production/book-authority/books/{book_id}/plan-changes", {
        "project_id": project_id, "workspace_id": workspace_id, "book_id": book_id, "actor_id": principal.principal_id,
        "trace_id": f"{project_id}:operator-proposal", "correlation_id": book_run_id,
        "stable_idempotency_key": f"{project_id}:operator-proposal", "source_type": "HUMAN_FEEDBACK",
        "source_evidence_version_id": feedback.asset_version_id, "target_asset_version_id": target_id,
        "proposed_asset_version_id": candidate_id,
    })
    proposal_id = proposal["proposal_id"]
    control = {"project_id": project_id, "actor_id": principal.principal_id}
    base = f"/product/production/book-authority/books/{book_id}/plan-changes/{proposal_id}"
    post(base + "/decisions", {**control, "approved": True, "reason": "Fixture operator future-plan exercise"})
    post(base + "/activate", control)
    resume_path = f"/product/production/book-authority/runs/{book_run_id}/plan-changes/{proposal_id}/resume"
    resumed = post(resume_path, control)
    replay = post(resume_path, control)
    assert replay["replayed"] is True
    assert replay["snapshot_id"] == resumed["snapshot_id"]
    new_snapshot = composition.input_resolver.require(resumed["snapshot_id"])
    assert new_snapshot.current_chapter_group_plan_version == candidate_id
    assert new_snapshot.narrative_chapter_cursor == 4
    assert authority.require(book_run_id)["accepted_through_chapter"] == 3
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT COUNT(*) FROM authority_book_production_input_binding WHERE book_run_id=%s", [book_run_id])
        assert uow.cursor.fetchone() == (2,)
    continued = drive(composition=composition, chapter=chapter, book_run_id=book_run_id, worker=worker,
                      events=records.append, maximum_ticks=180, deadline=time.monotonic() + 480)
    assert continued == "ACCEPTED_TARGET_REACHED", {"reason": continued, "events": records[-5:]}
    before_replay = authority.require(book_run_id)
    assert before_replay["accepted_through_chapter"] == 6
    assert post(resume_path, control)["replayed"] is True
    assert authority.require(book_run_id) == before_replay
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT chapter_number,chapter_outcome_asset_version_id,story_state_asset_version_id,canon_snapshot_asset_version_id FROM authority_book_chapter_acceptance WHERE book_run_id=%s AND chapter_number<=3 ORDER BY chapter_number", [book_run_id])
        assert uow.cursor.fetchall() == accepted_history
    return {"proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY", "book_run_id": book_run_id,
            "proposal_id": proposal_id, "input_snapshot_id": resumed["snapshot_id"], "accepted_chapters": 6, "checkpoint_chapter": 3}
