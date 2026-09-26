from dataclasses import replace
from uuid import uuid4

from psycopg.types.json import Jsonb
import pytest

from novel_forge.modules.authority_handler_runtime.contracts import AuthorityHandlerRequest, AuthorityInputAsset
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.application import MkaosAuthorityApplication, ApproveKnowledgeCandidateCommand
from novel_forge.modules.mkaos_authority.craft import core_catalog_hash, craft_hash
from novel_forge.modules.mkaos_authority.craft_authoring import AuthorCoreCraftCommand
from novel_forge.modules.mkaos_authority.domain import NarrativeIntelligenceNeed
from novel_forge.modules.mkaos_authority.query import MkaosAuthorityQuery
from novel_forge.modules.story_planning_runtime import GENERATOR_INPUT_ROLES, StoryPlanningGenerationApplication, StoryPlanningGenerationCommand
from novel_forge.modules.story_planning_runtime.application import _PlanningGenerationHandler, _command_payload
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, seed_authority_project_book
from tests.integration.test_core_functional_loops_postgres import RELEASE_SHA, _ExternalEffectPepFixturePlanningBinder, _activate_plan_chain, _principal, _seed_inputs
from tests.unit.test_story_planning_runtime import _realization_slice


def test_pg_frozen_selection_production_planning_handler_derives_exact_scene_strategy():
    ensure_migrated()
    project_id = "craft-planning:" + uuid4().hex
    workspace_id, book_id = "workspace:" + project_id, "book:" + project_id
    seed_authority_project_book(project_id=project_id, workspace_id=workspace_id, book_id=book_id)
    generic = _seed_inputs(project_id, book_id, target_chapter_count=3)
    principal = _principal(project_id)
    principal = replace(principal, permissions=principal.permissions | {"mkaos.authority.execute", "mkaos.authority.approve", "mkaos.authority.query"})
    planning = StoryPlanningGenerationApplication(DATABASE_URL, execution_binder=_ExternalEffectPepFixturePlanningBinder(), application_build_id="craft-planning-test", commit_sha=RELEASE_SHA, allow_scripted_evaluation_fixture=True)
    activated = _activate_plan_chain(project_id=project_id, workspace_id=workspace_id, book_id=book_id, generic=generic, principal=principal, application=planning)
    generic.update({"book_plan": activated["book_plan.generate"], "volume_plan": activated["volume_plan.generate"], "arc_plans": activated["arc_plan.generate"], "chapter_group_plan": activated["chapter_group_plan.generate"]})
    knowledge = MkaosAuthorityApplication(DATABASE_URL, application_build_id="craft-planning-test", commit_sha=RELEASE_SHA)
    catalog_hash = core_catalog_hash()
    authored = knowledge.execute_core_craft(AuthorCoreCraftCommand(project_id=project_id, workspace_id=workspace_id, mechanism_id="spatial-anchor", catalog_hash=catalog_hash, actor_id=principal.principal_id, idempotency_key="author", trace_id="trace:craft", correlation_id="correlation:craft"), principal=principal)
    knowledge.execute_approval(ApproveKnowledgeCandidateCommand(project_id=project_id, workspace_id=workspace_id, candidate_asset_version_id=authored["asset_version_id"], policy_version="repository-original-craft-v1:" + catalog_hash, rationale="Reviewed original abstract spatial mechanism for engineering protocol validation; no creative quality claim.", actor_id=principal.principal_id, idempotency_key="approve", trace_id="trace:craft", correlation_id="correlation:craft"), principal=principal)
    query = MkaosAuthorityQuery(DATABASE_URL)
    selection = query.resolve_narrative_intelligence(project_id=project_id, book_id=book_id, need=NarrativeIntelligenceNeed(scope="SCENE", target_stage="chapter_plan.generate", craft_context={"scene_goal": ["空间锚定，读者看清双方位置和退路。"], "chapter_number": 1}))
    assert len(selection["selected"]) == 1
    context = {"schema_version": "novelos.planning_context_bundle.v1", "project_id": project_id, "book_id": book_id, "narrative_intelligence": selection}
    context_id = "craft-planning-context:" + uuid4().hex
    context_version = context_id + ":v1"
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,'context_bundle')", [context_id, project_id])
        uow.cursor.execute("INSERT INTO authority_asset_version(asset_version_id,asset_id,version_number,lifecycle,eligibility,governance,content,content_hash,schema_version) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,'novelos.planning_context_bundle.v1')", [context_version, context_id, Jsonb(context), craft_hash(context)])
        uow.commit()
    command = StoryPlanningGenerationCommand(project_id=project_id, workspace_id=workspace_id, book_id=book_id, actor_id=principal.principal_id, generator_operation_name="chapter_plan.generate", logical_key="chapter:1", input_versions={role: generic[role] for role in GENERATOR_INPUT_ROLES["chapter_plan.generate"]}, parent_version_id=generic["chapter_group_plan"], narrative_realization=_realization_slice(parent_version_id=generic["chapter_group_plan"]), idempotency_key="planning:craft", trace_id="trace:craft", correlation_id="correlation:craft")

    class Binder(_ExternalEffectPepFixturePlanningBinder):
        invalid = False

        def execute(self, **kwargs):
            candidate = super().execute(**kwargs)
            payload = dict(candidate.candidate_payload)
            scene = payload["scene_plan"][0]
            field = next(key for key, value in scene.items() if isinstance(value, str) and len(value.strip()) >= 8 and not key.endswith(("_id", "_ref")))
            card = selection["selected"][0]
            payload["knowledge_translations"] = [{"knowledge_card_asset_version_id": card["knowledge_card_asset_version_id"], "content_hash": card["content_hash"], "decision": "ADAPT", "usage_role": "MECHANISM", "rationale": "在既定目标内建立可追踪的空间关系。", "prerequisite_resolution": "位置可被当前视角观察；不增加新事件或世界规则。", "use_sites": [{"target_pointer": f"/scene_plan/0/{field}", "realization_excerpt": scene[field], "expected_application": "让既定场景动作可定位。", "preservation_requirements": ["保留当前视角、因果与计划胜负。"], "verification_checks": ["正文出现可定位的起点与动作位移。"], "craft_role": "PRIMARY", "craft_sequence": 1, "intended_reader_effect": "读者可以追踪人物移动。"}]}]
            if self.invalid:
                payload["knowledge_translations"][0]["content_hash"] = "sha256:" + "0" * 64
            evidence = replace(candidate.evidence, context_bundle_asset_version_id=context_version, context_bundle_hash=craft_hash(context), narrative_intelligence_selection_digest=selection["selection_digest"])
            return replace(candidate, candidate_payload=payload, evidence=evidence)

    assets = AuthorityAssetQuery(DATABASE_URL)
    inputs = tuple(AuthorityInputAsset(asset_version_id=document.asset_version_id, asset_type=document.asset_type, content_hash=document.content_hash, content=document.content) for identity in command.input_versions.values() for document in [assets.require(project_id=project_id, asset_version_id=identity)])
    request = AuthorityHandlerRequest(operation_id="operation:craft-planning-protocol", project_id=project_id, workspace_id=workspace_id, actor_id=principal.principal_id, trace_id="trace:craft", correlation_id="correlation:craft", definition_name="story_planning.generate", definition_version="1.0.0", command={"payload": _command_payload(command)}, inputs=inputs, attempt_id="attempt:craft", fencing_token=1, worker_id="fixture:craft")
    binder = Binder()
    handler = _PlanningGenerationHandler(binder, DATABASE_URL)
    first = handler.execute(request)
    retry = handler.execute(replace(request, attempt_id="attempt:craft-retry", fencing_token=2))
    strategy = first.content["craft_strategy"]
    assert strategy == first.content["candidate_payload"]["craft_strategy"] == retry.content["craft_strategy"]
    assert strategy["selection_digest"] == selection["selection_digest"]
    assert strategy["uses"][0]["mechanism"] == selection["selected"][0]["selected_content"]["craft_mechanism"]
    assert strategy["uses"][0]["knowledge_card_asset_version_id"] in first.reference_asset_version_ids
    assert first.lifecycle == "CANDIDATE" and first.eligibility == "INELIGIBLE"
    assert first.evidence["fixture_protocol_only"] is True
    binder.invalid = True
    with pytest.raises(KernelError, match="PLANNING_KNOWLEDGE_TRANSLATION_DRIFT"):
        handler.execute(request)


@pytest.mark.parametrize("continue_after_acceptance,typed_usage", [(False, False), (True, False), (True, True)])
def test_pg_native_opening_planning_provider_receives_craft_and_activates_frozen_strategy(request, monkeypatch, continue_after_acceptance, typed_usage):
    from copy import deepcopy

    from novel_forge.modules.runtime_job import RuntimeJobAuthority
    from novel_forge.workers.book_authority import execute_book_coordination_claim, schedule_book_coordination_jobs
    from tests.integration import narrative_reality_vertical_support as native
    from tests.integration import test_core_functional_loops_postgres as core

    state = {}
    original_seed = core._seed_inputs

    def seed_with_approved_craft(project_id, book_id, **kwargs):
        kwargs["world_production_policy"] = {**(kwargs.get("world_production_policy") or {}), "context_token_budget": 16000}
        if typed_usage:
            kwargs["craft_budget_policy"] = {"schema_version": "narrative-craft-budget.v3", "mechanism_usage_types": {"choice-exposes-value": "staged"}}
        generic = original_seed(project_id, book_id, **kwargs)
        principal = _principal(project_id)
        principal = replace(principal, permissions=principal.permissions | {"mkaos.authority.execute", "mkaos.authority.approve", "mkaos.authority.query"})
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT workspace_id FROM authority_workspace WHERE project_id=%s", [project_id])
            workspace_id = uow.cursor.fetchone()[0]
        knowledge = MkaosAuthorityApplication(DATABASE_URL, application_build_id="native-craft-planning", commit_sha=RELEASE_SHA)
        catalog_hash = core_catalog_hash()
        authored = knowledge.execute_core_craft(AuthorCoreCraftCommand(project_id=project_id, workspace_id=workspace_id, mechanism_id="choice-exposes-value", catalog_hash=catalog_hash, actor_id=principal.principal_id, idempotency_key="craft:native:author", trace_id="trace:craft:native", correlation_id="correlation:craft:native"), principal=principal)
        approved = knowledge.execute_approval(ApproveKnowledgeCandidateCommand(project_id=project_id, workspace_id=workspace_id, candidate_asset_version_id=authored["asset_version_id"], policy_version="repository-original-craft-v1:" + catalog_hash, rationale="Editorial approval of original abstract choice mechanism; scripted engineering proof only.", actor_id=principal.principal_id, idempotency_key="craft:native:approve", trace_id="trace:craft:native", correlation_id="correlation:craft:native"), principal=principal)
        state.update(project_id=project_id, approved=approved)
        return generic

    class CraftPlanningTransport(native.NativeRealityTransportFixture):
        def __init__(self):
            super().__init__()
            self.rejected_scene = True
            self.chapter_inputs = []

        def __call__(self, stage, inputs):
            result = super().__call__(stage, inputs)
            if stage in {"review", "rereview"}:
                for check in result.get("craft_checks", []):
                    check.update(effect_status="ACHIEVED", reason="Scripted located realization for native feedback protocol; no reader-effect claim.")
                    for side in check["side_effects"]:
                        side.update(status="CLEAR", reason="Scripted negative side-effect control.")
                for check in result.get("craft_preservation_checks", []):
                    check.update(status="PRESERVED", reason="Scripted exact unchanged realization control.")
            return result

        def planning(self, stage, inputs):
            result = super().planning(stage, inputs)
            if stage == "world_candidates.evaluate":
                return result
            selection = inputs.get("narrative_intelligence") or (inputs.get("world_preparation") or {}).get("narrative_intelligence") or {}
            selected = selection.get("selected") or []
            if selected:
                result["knowledge_translations"] = []
            for card in selected:
                translation = {"knowledge_card_asset_version_id": card["knowledge_card_asset_version_id"], "content_hash": card["content_hash"], "decision": "REJECT", "usage_role": "MECHANISM", "rationale": "Reserve this conditional scene mechanism for the concrete Chapter choice; the higher plan retains its existing events.", "prerequisite_resolution": "No concrete scene use is being adopted at this planning scope.", "use_sites": []}
                if stage == "chapter_plan.generate":
                    scene = result["scene_plan"][0]
                    field = next(key for key, value in scene.items() if isinstance(value, str) and len(value.strip()) >= 8 and not key.endswith(("_id", "_ref")))
                    translation.update(decision="ADAPT", rationale="Expose the established protagonist priority through the planned choice and its existing cost.", prerequisite_resolution="The frozen realization includes a consequential protagonist choice. Preserve the established outcome and visible knowledge; avoid inventing an additional option or private motive.", use_sites=[{"target_pointer": f"/scene_plan/0/{field}", "realization_excerpt": scene[field], "expected_application": "Render the planned choice as an observable action with the existing cost instead of explaining a trait.", "preservation_requirements": ["Preserve the accepted choice, its consequence, current POV, character voice and knowledge boundary."], "verification_checks": ["Locate the choice action and its existing cost without added narrative facts."], "craft_role": "PRIMARY", "craft_sequence": 1, "intended_reader_effect": "The reader infers the protagonist priority from the consequential choice."}])
                if typed_usage and stage == "chapter_plan.generate":
                    history = card["craft_assessment"]["budget_assessment"]["accepted_usage_history"]
                    previous = next((row for row in history if row["effect_status"] == "ACHIEVED"), None)
                    translation["use_sites"][0]["craft_combination"] = dict(narrative_problem="Make the established choice legible.", selection_reason="The scene already contains a consequential decision.", role_and_order_reason="Show the choice before its cost.", combined_effect="The reader infers priority from action.", interference_risk="Explanatory commentary would dilute the choice.", preservation_constraint="Retain outcome, voice and knowledge boundaries.", abstain_condition="Do not add a choice to a scene without one.")
                    translation["use_sites"][0]["craft_usage"] = {
                        "instance_id": previous["usage"]["instance_id"] if previous else "",
                        "predecessor_use_id": previous["use_id"] if previous else "",
                        "phase": "DEVELOPMENT" if previous else "SETUP",
                        "scope_id": selection["need"]["craft_context"]["usage_scope_context"]["arc_plan_version_ids"][0],
                    }
                result["knowledge_translations"].append(translation)
            if stage == "chapter_plan.generate":
                self.chapter_inputs.append(deepcopy(inputs))
            return result

    def drive_native_planning(*, composition, chapter_application, snapshot, generic, transport):
        admitted = native.admit_native_production(composition=composition, snapshot=snapshot, generic=generic)
        jobs = RuntimeJobAuthority(DATABASE_URL)
        generation_operation = ""
        for _ in range(20):
            schedule_book_coordination_jobs(composition.query, jobs, limit=1, book_run_id=admitted.book_run_id)
            claim = jobs.claim(runtime_group="book", worker_id="native-craft-planning-worker", lease_seconds=30, job_kinds=("BOOK_COORDINATION_TICK",), subject_kind="BOOK_RUN", subject_id=admitted.book_run_id)
            assert claim is not None
            tick = execute_book_coordination_claim(jobs, composition, claim)
            if tick["action"] == "GENERATE_CHAPTER_PLAN":
                generation_operation = tick["operation_id"]
            if tick["action"] == "FREEZE_CHAPTER_PLAN":
                break
            assert tick["action"] != "DISPATCH_CHAPTER"
        else:
            raise AssertionError("Native Book supervisor did not activate and freeze the Chapter plan")
        assert generation_operation
        generation = composition.planning.require_generation(generation_operation)
        assert generation["status"] == "ACTIVE"
        candidate_version = generation["candidate_asset_version_id"]
        assets = AuthorityAssetQuery(DATABASE_URL)
        candidate = assets.require(project_id=snapshot.project_id, asset_version_id=candidate_version)
        strategy = candidate.content["craft_strategy"]
        assert strategy == candidate.content["candidate_payload"]["craft_strategy"]
        assert len(strategy["uses"]) == 1
        assert strategy["uses"][0]["mechanism_id"] == "choice-exposes-value"
        execution_plan = composition.query.require_chapter_execution_plan(candidate_version)
        assert execution_plan["content"]["craft_strategy"] == strategy
        assert len(transport.chapter_inputs) == 1
        delivered = transport.chapter_inputs[0]["narrative_intelligence"]
        assert len(delivered["selected"]) == 1 < delivered["craft_policy"]["max_craft_candidates"]
        assert delivered["selection_digest"] == strategy["selection_digest"]
        assert delivered["selected"][0]["selected_content"]["craft_mechanism"] == strategy["uses"][0]["mechanism"]
        assert delivered["need"]["craft_context"]["scene_goal"]
        assert delivered["need"]["craft_context"]["chapter_number"] == 1
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT request_payload, external_effect_id FROM authority_external_effect WHERE operation_id=%s AND request_payload->>'stage'='chapter_plan.generate'", [generation_operation])
            effect_rows = uow.cursor.fetchall()
            uow.cursor.execute("SELECT version.content FROM authority_operation_output_asset AS binding JOIN authority_asset_version AS version ON version.asset_version_id=binding.asset_version_id WHERE binding.operation_id=%s AND binding.output_key='planning.context_bundle'", [generation_operation])
            frozen_context = uow.cursor.fetchone()[0]
        assert len(effect_rows) == 1
        payload, effect_id = effect_rows[0]
        assert payload["input"]["narrative_intelligence"] == delivered == frozen_context["narrative_intelligence"]
        runtime = payload["_production_execution"]["capability_runtime"]
        admission = assets.require(project_id=snapshot.project_id, asset_version_id=runtime["provider_admission_asset_version_id"]).content["contract"]
        assert admission["provider_admission"]["status"] == "ADMITTED"
        materialization = assets.require(project_id=snapshot.project_id, asset_version_id=runtime["materialization_asset_version_id"]).content["contract"]
        output_schema = materialization["output_schema"]["content"]
        assert "knowledge_translations" in output_schema["required"]
        site_schema = output_schema["properties"]["knowledge_translations"]["items"]["properties"]["use_sites"]["items"]
        assert {"craft_role", "craft_sequence", "intended_reader_effect"} <= set(site_schema["required"])
        from novel_forge.modules.chapter_authority.execution_gateway import _materialize_production_codex_prompt
        from novel_forge.modules.production_execution.contracts import TargetScope

        frozen_command = composition.planning._generation_command(generation_operation)
        prompt, prompt_evidence = _materialize_production_codex_prompt(target_scope=TargetScope(scope_kind=frozen_command.planning_scope.value.lower(), scope_id=frozen_command.logical_key, project_id=snapshot.project_id, book_id=snapshot.book_id).to_dict(), stage="chapter_plan.generate", inputs=payload["input"], materialization=materialization)
        assert prompt_evidence["fully_rendered_prompt_hash"] == admission["prompt_materialization"]["fully_rendered_prompt_hash"]
        assert strategy["uses"][0]["mechanism"]["abstract_mechanism"] in prompt
        assert "choice-exposes-value" in prompt and "craft_sequence" in prompt
        replay = composition.planning.generate(frozen_command, principal=composition.principal)
        assert replay.candidate_asset_version_id == candidate_version
        assert len(transport.chapter_inputs) == 1
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT external_effect_id FROM authority_external_effect WHERE operation_id=%s AND request_payload->>'stage'='chapter_plan.generate'", [generation_operation])
            assert uow.cursor.fetchall() == [(effect_id,)]
        state["native_proof"] = {"book_run_id": admitted.book_run_id, "generation_operation_id": generation_operation, "candidate_asset_version_id": candidate_version, "selection_digest": delivered["selection_digest"], "strategy_digest": strategy["strategy_digest"], "external_effect_id": effect_id, "proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY"}
        if continue_after_acceptance:
            from novel_forge.modules.chapter_authority.contracts import ChapterNode
            from novel_forge.modules.mkaos_authority.runtime_usage import list_accepted_craft_usage
            from novel_forge.modules.authority_security import Principal, PrincipalType
            worker = Principal(principal_id="native-craft-worker", principal_type=PrincipalType.WORKER,
                permissions=composition.principal.permissions - {"book.authority.approve_replan"},
                project_scope=composition.principal.project_scope, authentication_source="scripted-native-worker")
            first_usage = None
            for _ in range(60):
                schedule_book_coordination_jobs(composition.query, jobs, limit=1, book_run_id=admitted.book_run_id)
                claim = jobs.claim(runtime_group="book", worker_id="native-craft-planning-worker", lease_seconds=30,
                    job_kinds=("BOOK_COORDINATION_TICK",), subject_kind="BOOK_RUN", subject_id=admitted.book_run_id)
                assert claim is not None
                tick = execute_book_coordination_claim(jobs, composition, claim)
                if tick["action"] == "DISPATCH_CHAPTER":
                    scheduler = chapter_application.scheduler(principal=worker)
                    for _ in range(len(ChapterNode) * 2 + 4):
                        chapter_tick = scheduler.tick(project_id=snapshot.project_id, root_operation_id=tick["operation_id"])
                        if chapter_tick.saga_status == "SUCCEEDED":
                            break
                    else:
                        raise AssertionError("Native Craft Chapter failed before acceptance: " + str(chapter_tick))
                accepted_through = composition.authority.require(admitted.book_run_id)["accepted_through_chapter"]
                if accepted_through >= 1 and first_usage is None:
                    first_usage = list_accepted_craft_usage(DATABASE_URL, project_id=snapshot.project_id, book_id=snapshot.book_id)
                    assert first_usage and all(row["usage_basis"] == "ACCEPTED_PROSE_REVIEW" for row in first_usage)
                if accepted_through >= 2:
                    break
            else:
                raise AssertionError("Native Craft chain did not reach a second acceptance")
            assert len(transport.chapter_inputs) == 2
            later = transport.chapter_inputs[-1]["narrative_intelligence"]
            if typed_usage:
                continued = later["selected"][0]
                assert continued["craft_assessment"]["budget_assessment"]["frequency"] == 1
                assert continued["craft_assessment"]["budget_assessment"]["temporal_budget_applied"] is False
                final_usage = list_accepted_craft_usage(DATABASE_URL, project_id=snapshot.project_id, book_id=snapshot.book_id)
                assert {row["usage"]["phase"] for row in final_usage} == {"SETUP", "DEVELOPMENT"}
                assert len({row["usage"]["instance_id"] for row in final_usage}) == 1
                assert final_usage[0]["usage"]["accepted_predecessor"]["acceptance_id"] == first_usage[0]["acceptance_id"]
                state["native_proof"]["accepted_phase_usage"] = final_usage
                historical = list_accepted_craft_usage(DATABASE_URL, project_id=snapshot.project_id, book_id=snapshot.book_id, limit=0, include_continuing=True)
                assert historical == [final_usage[0]]
                assert list_accepted_craft_usage(DATABASE_URL, project_id=snapshot.project_id, book_id=snapshot.book_id, limit=0) == []
                with pytest.raises(KernelError, match="CRAFT_CONTINUATION_HISTORY_BUDGET_EXHAUSTED"):
                    list_accepted_craft_usage(DATABASE_URL, project_id=snapshot.project_id, book_id=snapshot.book_id, limit=100, include_continuing=True, continuation_acceptance_limit=1)
                from types import SimpleNamespace
                from tests.integration.test_longform_prose_editorial_postgres import _automatic_review
                coordinator, scope, model, review_id = _automatic_review(
                    {"project_id": snapshot.project_id, "workspace_id": snapshot.workspace_id, "principal": composition.principal, "book": SimpleNamespace(book_run_id=admitted.book_run_id)},
                    relation_window_limit=2, relation_retrieval_version="accepted-state-relations.v2",
                )
                for _ in range(20):
                    progress = coordinator.automatic_tick(**scope, run_id=review_id)
                    if progress.get("review_complete"):
                        break
                assert progress["review_complete"]
                relations = [window for window in progress["manifest"]["windows"] if window.get("relation_hypothesis")]
                assert relations and all(window["relation_hypothesis"]["basis"] == "ACCEPTED_STATE_IDENTITIES_AND_CAUSES" for window in relations)
                assert {span["chapter_number"] for window in relations for span in window["spans"]} == {1, 2}
                assert all(row["indexed"] > 0 for row in progress["manifest"]["relation_retrieval"]["source_coverage"])
                state["native_proof"]["accepted_state_review"] = {"run_id": review_id, "manifest_digest": progress["manifest"]["manifest_digest"], "relation_windows": len(relations), "real_model_call": False}
            else:
                cooled = next(row for row in later["rejected"] if row["knowledge_card_asset_version_id"] == strategy["uses"][0]["knowledge_card_asset_version_id"])
                assert cooled["reason"] == "CRAFT_COOLDOWN"
                assert cooled["craft_assessment"]["budget_assessment"]["recent_usage"] == first_usage
                assert cooled["craft_assessment"]["budget_assessment"]["frequency"] == 1
            assert later["need"]["craft_context"]["chapter_number"] == 2
            assert first_usage[0]["effect_status"] == "ACHIEVED"
            state["native_proof"].update(accepted_through_chapter=accepted_through,
                accepted_usage=first_usage, next_selection_digest=later["selection_digest"])
            import json
            import os
            from pathlib import Path
            if os.environ.get("NARRATIVE_CRAFT_NATIVE_EVIDENCE_PATH"):
                Path(os.environ["NARRATIVE_CRAFT_NATIVE_EVIDENCE_PATH"]).write_text(json.dumps(state["native_proof"], ensure_ascii=False, indent=2))
        return state["native_proof"]

    monkeypatch.setattr(core, "_seed_inputs", seed_with_approved_craft)
    monkeypatch.setattr(native, "NativeRealityTransportFixture", CraftPlanningTransport)
    monkeypatch.setattr(native, "execute_native_reality_vertical", drive_native_planning)
    core.test_open_book_runs_foundation_search_and_snapshot_vertical_in_postgres(request=request, autonomous_world=False, craft_budget_policy={"schema_version": "narrative-craft-budget.v3", "mechanism_usage_types": {"choice-exposes-value": "staged"}} if typed_usage else None)
    assert state["native_proof"]["candidate_asset_version_id"]
