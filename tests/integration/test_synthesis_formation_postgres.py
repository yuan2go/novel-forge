from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json

import pytest

from novel_forge.api.authority_dependencies import (
    build_book_production_composition,
    build_chapter_authority_application,
    build_production_execution_composition,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.book_design_authority.formation import (
    StartStoryFormationCommand,
)
from novel_forge.modules.book_design_authority.formation_domain import (
    StoryFormationInput,
    deterministic_story_formation_run_id,
)
from novel_forge.modules.authority_security import TrustedPrincipalResolver
from novel_forge.modules.capability_packs.longform_profiles import (
    build_story_planning_pack_profile,
)
from novel_forge.modules.content_authority.application import (
    ContentAuthorityApplication,
    ContentOperationRequest,
)
from novel_forge.modules.content_authority.codecs import CONTENT_CODECS
from novel_forge.modules.provider_control.registry import ProviderAdapterRegistry
from novel_forge.modules.story_planning_runtime import (
    story_planning_generation_definition,
)
from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.workers.book_authority import execute_story_formation_claim
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.capability_pack_postgres_support import (
    CapabilityPackPostgresHarness,
    RELEASE_SHA,
)
from tests.integration.synthesis_production_support import SynthesisTransport
from tests.integration.test_core_functional_loops_postgres import _principal


@pytest.mark.parametrize(
    "author_guided,result_repair,runtime_recovery,evaluation_recovery,manual_review,advice_only,target_chapters",
    [
        pytest.param(False, False, False, False, False, False, 3, id="current-production"),
        pytest.param(True, False, False, False, False, False, 3, id="author-guided"),
        pytest.param(False, True, False, False, False, False, 3, id="result-repair"),
        pytest.param(False, False, True, False, False, False, 3, id="legacy-runtime-recovery"),
        pytest.param(False, False, False, True, False, False, 3, id="evaluation-recovery"),
        pytest.param(False, False, False, False, True, False, 3, id="manual-second-candidate"),
        pytest.param(False, False, False, False, False, True, 3, id="advice-only-production"),
        pytest.param(False, False, False, False, False, False, 1, id="single-chapter-production"),
    ],
)
def test_native_formation_generates_foundation_from_author_brief(
    tmp_path, monkeypatch, author_guided, result_repair, runtime_recovery,
    evaluation_recovery, manual_review, advice_only, target_chapters,
    *, complete_after_result_repair=False, creative_validation=False, author_result_repair=False, valid_result_admission=False, capacity_continuation=False, capacity_policy_upgrade=False, semantic_repair=False, route_continuation=False, input_order_continuation=False, world_result_repair=False, world_disabled=False, world_optional_recovery=False, gateway_null_recovery=False, stage_repair_recovery=False, memo_timeout_recovery=False, memo_timeout_prefix_recovery=False, scene_core_recovery=False, scene_information_recovery=False, review_knowledge_recovery=False, length_scope_recovery=False, foundation_uncertainty_recovery=False, completed_release_recovery=False,
):
    if memo_timeout_prefix_recovery:
        memo_timeout_recovery = True
    if memo_timeout_recovery or scene_core_recovery or scene_information_recovery or review_knowledge_recovery or length_scope_recovery:
        from tests.integration.synthesis_production_support import freeze_current_chapter_bundle
        freeze_current_chapter_bundle(monkeypatch)
    if scene_core_recovery or scene_information_recovery or review_knowledge_recovery or length_scope_recovery:
        from novel_forge.modules.chapter_authority import definitions as scene_definitions
        saved_draft_version = scene_definitions.CHAPTER_DRAFT_DEFINITION_VERSION
        saved_review_version = scene_definitions.CHAPTER_REVIEW_DEFINITION_VERSION
        saved_canon_version = scene_definitions.CHAPTER_CANON_DEFINITION_VERSION
        saved_revision_version = scene_definitions.CHAPTER_REVISION_DEFINITION_VERSION
        saved_support_version = scene_definitions.CHAPTER_SUPPORT_DEFINITION_VERSION
        if length_scope_recovery:
            monkeypatch.setattr(scene_definitions, "CHAPTER_CANON_DEFINITION_VERSION", "3.9.0")
            monkeypatch.setattr(scene_definitions, "CHAPTER_SUPPORT_DEFINITION_VERSION", "3.9.0")
            monkeypatch.setattr(scene_definitions, "CHAPTER_REVISION_DEFINITION_VERSION", "3.9.0")
        elif review_knowledge_recovery:
            monkeypatch.setattr(scene_definitions, 'CHAPTER_REVIEW_DEFINITION_VERSION', '3.9.0')
        else:
            monkeypatch.setattr(scene_definitions, 'CHAPTER_DRAFT_DEFINITION_VERSION', '3.9.1' if scene_information_recovery else '3.9.0')
        normal_scene_read = Path.read_text
        def legacy_scene_manifest(path, *args, **kwargs):
            value = normal_scene_read(path, *args, **kwargs)
            if path.name != 'chapter_generation_pack.json':
                return value
            from novel_forge.storage.authority_repositories import definition_hash
            value = json.loads(value)
            value['identity']['version'] = '2.16.0' if length_scope_recovery else '2.15.0' if review_knowledge_recovery else '2.14.0' if scene_information_recovery else '2.13.0'
            definitions = {d['name']: d for d in scene_definitions.chapter_operation_definitions(application_build_id='legacy-scene-fixture', commit_sha='0'*40, model_effects_required=True)}
            for node in value['workflow_template']['nodes']:
                node['operation_definition_ref'] = node['operation_name'] + '@' + definitions[node['operation_name']]['definition_version']
                node['operation_definition_hash'] = definition_hash(definitions[node['operation_name']])
            return json.dumps(value)
        monkeypatch.setattr(Path, 'read_text', legacy_scene_manifest)
    if memo_timeout_recovery:
        import sys
        current_chapter_builder = build_chapter_authority_application
        def historical_chapter_builder(*args, **kwargs):
            application = current_chapter_builder(*args, **kwargs)
            application.registry.coordinated_contract = False
            return application
        monkeypatch.setattr(sys.modules[__name__], "build_chapter_authority_application", historical_chapter_builder)
        from novel_forge.modules.chapter_authority import execution_gateway as memo_gateway
        from novel_forge.modules.capability_packs import operation_catalog as memo_catalog
        from novel_forge.modules.production_execution import CapabilityId
        monkeypatch.setitem(memo_gateway._STAGE_CAPABILITIES, 'memo', CapabilityId.PLANNING_CHAPTER_GENERATE)
        monkeypatch.setitem(memo_catalog._NON_PROVIDER_CAPABILITIES, 'memo', 'planning.chapter.generate')
        normal_read_text=Path.read_text
        def legacy_manifest(path,*args,**kwargs):
            value=normal_read_text(path,*args,**kwargs)
            if path.name!='chapter_generation_pack.json':
                return value
            from novel_forge.modules.chapter_authority.definitions import chapter_operation_definitions
            from novel_forge.storage.authority_repositories import definition_hash
            value=json.loads(normal_read_text(Path(__file__).resolve().parents[2] / 'config/capability_packs/historical/chapter_generation_pack_2_26_0.json'))
            value['identity']['version'] = '2.12.0'
            value['workflow_template']['workflow_version'] = '3.8.0'
            definitions={d['name']:d for d in chapter_operation_definitions(application_build_id='legacy-fixture',commit_sha='0'*40,model_effects_required=True)}
            for node in value['workflow_template']['nodes']:
                node['operation_definition_ref']=node['operation_name']+'@'+definitions[node['operation_name']]['definition_version']
                node['operation_definition_hash']=definition_hash(definitions[node['operation_name']])
                if node['node_id']=='memo':
                    node['timeout_policy_ref']='timeout:planning-chapter-generate:v1'
                    node['capability_id']='planning.chapter.generate'
            return json.dumps(value)
        monkeypatch.setattr(Path,'read_text',legacy_manifest)
    old_chapter_constants = {}
    if memo_timeout_recovery:
        from novel_forge.modules.chapter_authority import definitions as chapter_definitions
        from novel_forge.modules.chapter_authority.contracts import ChapterNode
        for key,value in {
            'CHAPTER_MODEL_EFFECT_DEFINITION_VERSION':'3.8.0',
            'CHAPTER_AUTHOR_INPUT_DEFINITION_VERSION':'3.8.0-author-input.v2',
            'CHAPTER_MODEL_WORKFLOW_DEFINITION_VERSION':'3.8.0',
            'CHAPTER_MODEL_WORKFLOW_DEFINITION_REF':'chapter_authority_slice@3.8.0',
            'CHAPTER_LONG_TIMEOUT_POLICY_NODES':chapter_definitions.CHAPTER_LONG_TIMEOUT_POLICY_NODES-{ChapterNode.MEMO},
        }.items():
            old_chapter_constants[key]=getattr(chapter_definitions,key)
            monkeypatch.setattr(chapter_definitions,key,value)
    fixture_production_profile = {"world_production_policy": {"context_token_budget": 16000},
        "chapter_context_policy": {"version": "book-chapter-context.v1", "draft_profile": "draft-context-profile-v4", "draft_token_budget": 128000, "quality_token_budget": 128000}}
    if advice_only:
        from novel_forge.modules.review.prose_window import WINDOW_POLICY

        fixture_production_profile["cross_chapter_review_policy"] = {
            "version": WINDOW_POLICY, "source_token_budget": 8000,
        }
    harness = CapabilityPackPostgresHarness(
        "synthesis-formation-author" if author_guided else "synthesis-formation",
        production_profile=fixture_production_profile,
    )
    from copy import copy

    chapter_pack = copy(harness)
    chapter_pack.pack_id += "-chapter"
    if creative_validation:
        from tests.integration.creative_validation_production_support import prepare_native_template
        template_actor = prepare_native_template(harness, chapter_pack, bounded_repairs=(semantic_repair or world_result_repair) and not route_continuation,world_disabled=world_disabled,contract_recovery=scene_information_recovery or review_knowledge_recovery or length_scope_recovery,optional_memo=memo_timeout_recovery)
    else:
        approved_chapter = chapter_pack.register_compile_approve(
            "1.0.0",
            generation=1,
            approval_scope=chapter_pack.approval_scope(
                environments=("test",), runtime_profiles=("test",)
            ),
            target_runtime_profile="test",
        )
        chapter_pack.register_agents(approved_chapter.compiled)
        chapter_deployment = chapter_pack.deploy(
            approved_chapter, environment="test", runtime_profile="test"
        )
        chapter_pack.activate(chapter_deployment, environment="test")
    from tests.integration.test_postgresql_only_chapter_slice import (
        PostgreSQLOnlyChapterSliceTests,
    )

    PostgreSQLOnlyChapterSliceTests.release_evidence(harness.project_id)
    historical = pytest.MonkeyPatch() if runtime_recovery else None
    if historical:
        import novel_forge.modules.capability_packs.longform_profiles as profiles
        import novel_forge.modules.story_planning_runtime.application as planning_module
        import novel_forge.modules.book_design_authority.formation_generation as formation_generation
        original_command = formation_generation.StoryPlanningGenerationCommand
        historical.setattr(profiles, "STORY_PLANNING_OPERATION_DEFINITION_REF", "story_planning.generate@1.15.0")
        historical.setattr(planning_module, "STORY_PLANNING_GENERATION_VERSION", "1.15.0")
        historical.setattr(formation_generation, "StoryPlanningGenerationCommand", lambda **values: replace(original_command(**values), execution_contract_version="1.15.0"))
    from novel_forge.modules.story_planning_runtime.application import STORY_PLANNING_GENERATION_VERSION
    selected_planning_version = '1.15.0' if runtime_recovery else '1.18.0' if memo_timeout_recovery else STORY_PLANNING_GENERATION_VERSION
    legacy_memo_planning_command = None
    if memo_timeout_recovery:
        from novel_forge.modules.book_design_authority import formation_generation as memo_formation_generation
        from novel_forge.modules.story_planning_runtime import application as memo_planning_application
        from novel_forge.modules.book_authority import input_resolver as memo_input_resolver
        monkeypatch.setattr(memo_input_resolver, 'STORY_PLANNING_OPERATION_DEFINITION_REF', 'story_planning.generate@1.18.0')
        monkeypatch.setattr(memo_planning_application, 'STORY_PLANNING_GENERATION_VERSION', '1.18.0')
        legacy_memo_planning_command = memo_formation_generation.StoryPlanningGenerationCommand
        from novel_forge.modules.book_authority import opening as memo_opening, supervisor as memo_supervisor
        memo_planning_owners = (memo_formation_generation, memo_opening, memo_supervisor)
        for owner in memo_planning_owners:
            monkeypatch.setattr(owner, 'StoryPlanningGenerationCommand',
                lambda **values: replace(legacy_memo_planning_command(**values), execution_contract_version='1.18.0'))
    definition = story_planning_generation_definition(
        application_build_id="synthesis-formation", commit_sha=RELEASE_SHA,
        definition_version=selected_planning_version,
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.repositories.definitions.register(definition)
        uow.cursor.execute(
            "SELECT definition_hash FROM authority_operation_definition WHERE name=%s AND definition_version=%s",
            [definition["name"], definition["definition_version"]],
        )
        digest = str(uow.cursor.fetchone()[0])
        uow.commit()
    profile = build_story_planning_pack_profile(
        Path(__file__).resolve().parents[2],
        operation_definition_hash=digest,
        pack_id=harness.pack_id,
        execution_contract_version=selected_planning_version,
        **({"complete_request_capacity": False, "semantic_context_compression": False} if capacity_policy_upgrade else {}),
    )
    harness._base_manifest, harness._base_catalog = (
        profile.manifest,
        profile.artifact_catalog,
    )
    approval = harness.approval_scope(
        environments=("test",), runtime_profiles=("test",)
    )
    approval["allowed_workflow_definition_refs"] = [profile.workflow_ref]
    if creative_validation:
        from tests.integration.creative_validation_production_support import install_planning
        install_planning(harness, profile, template_actor)
    else:
        approved = harness.register_compile_approve(
            "1.1.0",
            generation=1,
            approval_scope=approval,
            target_runtime_profile="test",
            proof_skill_ref=profile.agent_skill_ref,
        )
        harness.register_agents(approved.compiled)
        deployment = harness.deploy(approved, environment="test", runtime_profile="test")
        harness.activate(deployment, environment="test")
    principal = _principal(harness.project_id)
    principal = replace(
        principal,
        permissions=principal.permissions
        | {
            "content.authority.execute",
            *(f"content.operation:{name}" for name in CONTENT_CODECS),
        },
    )
    content = ContentAuthorityApplication(
        DATABASE_URL,
        application_build_id="synthesis-formation",
        commit_sha=RELEASE_SHA,
        integration_proven=CONTENT_CODECS,
        trusted_only=True,
    )
    from tests.integration.synthesis_author_input_support import author_fixture, AuthorSynthesisTransport
    author = author_fixture(harness.project_id, harness.book_ids[0]) if author_guided else None
    brief = content.execute(
        ContentOperationRequest(
            definition_name="creative.brief.create",
            project_id=harness.project_id,
            workspace_id=harness.workspace_id,
            actor_id=principal.principal_id,
            trace_id="trace:synthesis-brief",
            correlation_id=harness.project_id,
            idempotency_key=f"{harness.project_id}:synthesis:brief",
            payload={
                "input_selection": {"contract_version": "creative-input-selection.v1", "book_id": harness.book_ids[0], "source_kind": "HISTORICAL_TEST_SAMPLE", "purpose": "ENGINEERING_REGRESSION", "intent_ref": "explicit-test-case"},
                "brief": {
                    "creative_brief_contract_version": "creative-brief-v3" if author_guided else "creative-brief-v2",
                    **({"author_design": author} if author_guided else {}),
                    "idea": "一名制图学徒发现街区正在被公共档案抹去，她必须决定是否公开会牵连证人的不完整证据。",
                    "genre": "speculative mystery",
                    "audience": "adult mystery readers",
                    "constraints": ["知识有来源；每次公开发现都需付出代价"],
                    "source_boundaries": [
                        "Only original expression; no reference prose"
                    ],
                }
            },
        ),
        principal=principal,
    )
    env = {
        "NOVEL_FORGE_ENVIRONMENT": "test",
        "NOVEL_FORGE_TEST_ALLOW_SCRIPTED_NARRATIVE_EVALUATION_FIXTURE": "true",
        "NOVEL_FORGE_APPLICATION_BUILD_ID": "synthesis-formation",
        "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
        "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
        "NOVEL_FORGE_PLANNING_PROVIDER": "scripted_provider_v2",
        "NOVEL_FORGE_PLANNING_MODEL": "synthesis-scripted",
        "NOVEL_FORGE_PLANNING_REASONING_EFFORT": "high",
        "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(tmp_path),
        "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": harness.pack_id,
        "NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID": chapter_pack.pack_id,
        "NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE": harness.project_id,
    }
    settings = IndustrialSettings(
        root=str(tmp_path),
        environment="test",
        storage_authority="postgresql",
        database_url=DATABASE_URL,
    )
    registry = ProviderAdapterRegistry()
    transport = AuthorSynthesisTransport(author, brief) if author_guided else SynthesisTransport()
    transport.database_url = settings.database_url
    if foundation_uncertainty_recovery:
        from novel_forge.modules.story_planning_runtime import application as planning_module
        resolved_check = planning_module.require_resolved_foundation_applicability
        monkeypatch.setattr(planning_module, "require_resolved_foundation_applicability", lambda _: None)
        original_foundation = transport.planning
        uncertain_once = False
        def uncertain_world(stage, inputs):
            nonlocal uncertain_once
            result = original_foundation(stage, inputs)
            if stage == "world.design.generate" and not uncertain_once:
                uncertain_once = True
                result["rules"][0]["cost"] = None
                item = next(item for item in result["applicability"]
                            if item["field_path"] in {"$.rules[0].cost", "/rules/0/cost"})
                item.update(status="UNDETERMINED", rationale="Retained uncertainty before Foundation activation")
            return result
        transport.planning = uncertain_world
        legacy_candidate = None
    if valid_result_admission:
        from novel_forge.modules.story_planning_runtime import result_recovery
        from novel_forge.modules.command_kernel.errors import KernelError
        normal_validation = result_recovery.validate_raw_result
        old_parser_rejected = False
        def reject_valid_result_once(generator, raw, **kwargs):
            nonlocal old_parser_rejected
            if generator == "world.design.generate" and not old_parser_rejected:
                old_parser_rejected = True
                raise KernelError("FOUNDATION_APPLICABILITY_INVALID", "old parser rejected an exact optional field path")
            return normal_validation(generator, raw, **kwargs)
        monkeypatch.setattr(result_recovery, "validate_raw_result", reject_valid_result_once)
        monkeypatch.setattr(result_recovery, "MAXIMUM_RESULT_REPAIRS", 0)
        original_admission_chapter = transport.chapter
        class AdmissionChapterTransport:
            @property
            def database_url(self):
                return getattr(original_admission_chapter, "database_url", "")
            @database_url.setter
            def database_url(self, value):
                original_admission_chapter.database_url = value
            def __call__(self, stage, inputs):
                value = original_admission_chapter(stage, inputs)
                if stage in {"draft", "revision"}:
                    from copy import deepcopy
                    from novel_forge.modules.chapter_authority.realization_composition import serialize_realization
                    value["scene_artifacts"][0]["text"] += "她收起信件，沿着来时的路走了回去。"
                    value["text"] = serialize_realization(value["scene_artifacts"])
                    original_admission_chapter.calls[-1]["output"] = deepcopy(value)
                return value
            def __getattr__(self, name):
                return getattr(original_admission_chapter, name)
        transport.chapter = AdmissionChapterTransport()
    if author_result_repair:
        original_author_planning = transport.planning
        damaged_author_decision = False

        def malformed_author_once(stage, inputs):
            nonlocal damaged_author_decision
            result = original_author_planning(stage, inputs)
            if stage == "reader.promise.generate" and not damaged_author_decision:
                damaged_author_decision = True
                result["author_design_decisions"][0]["realization_excerpt"] = "不存在的作者采纳摘录"
            return result

        transport.planning = malformed_author_once
    if advice_only:
        from tests.integration.synthesis_production_support import AdviceOnlySynthesisChapterTransport

        transport.chapter = AdviceOnlySynthesisChapterTransport()
    if result_repair:
        normal_planning = transport.planning
        damaged_world = False

        def malformed_once(stage, inputs):
            nonlocal damaged_world
            result = normal_planning(stage, inputs)
            if stage == "world.design.generate" and not damaged_world:
                damaged_world = True
                world = json.loads(result["world_foundation_json"])
                world["compiled_scope"] = ["BOOK", "VOLUME", "ARC"]
                result["world_foundation_json"] = json.dumps(world)
            return result

        transport.planning = malformed_once
    method_planning = transport.planning
    def declared_current_method_fixture(stage, inputs):
        result = method_planning(stage, inputs)
        if stage == 'chapter_plan.generate' and inputs.get('planning_command', {}).get('execution_contract_version') in {'1.19.0', '1.20.0', '1.21.0'}:
            result['chapter_contract_schema_version'] = 'chapter-mission-scene.v4'
            result['serialization_function'] = None if creative_validation else 'payoff_and_new_obligation'
        return result
    transport.planning = declared_current_method_fixture
    if creative_validation:
        normal_planning = transport.planning
        def consistent_fixture(stage, inputs):
            result = normal_planning(stage, inputs)
            if stage == "creative.candidates.generate":
                result["serialization_potential"] = None
                for declaration in result.get("applicability", []):
                    if declaration["field_path"] in {"$.serialization_potential", "/serialization_potential"}:
                        declaration.update(status="NOT_APPLICABLE", rationale="Bounded fixture work")
            def bounded_serialization(value):
                if isinstance(value, dict):
                    for key, child in value.items():
                        if key == "serialization_function":
                            value[key] = None
                        else:
                            bounded_serialization(child)
                elif isinstance(value, list):
                    for child in value:
                        bounded_serialization(child)
            bounded_serialization(result)
            return result
        transport.planning = consistent_fixture
    if world_optional_recovery:
        normal_world = transport.planning
        def rejected_world_future(stage, inputs):
            result = normal_world(stage, inputs)
            if stage == 'world_candidates.generate':
                for candidate in result['candidates']:
                    payload = json.loads(candidate['transition']['payload_json'])
                    payload['requirements'] = [{
                        'requirement_id': 'known-world-condition-unmet',
                        'state_kind': payload['state_kind'], 'entity_key': payload['entity_key'],
                        'field': 'status', 'operator': 'EQUALS', 'value': 'CLOSED',
                    }]
                    candidate['transition']['payload_json'] = json.dumps(payload)
                    candidate['preparation_paths'] = []
            return result
        transport.planning = rejected_world_future
    if world_result_repair:
        if world_result_repair == "reference-checkpoint":
            from copy import deepcopy
            from novel_forge.modules.story_planning_runtime.world_preparation import PlanningWorldPreparation, PlanningProviderStage
            from novel_forge.modules.command_kernel.worker_execution import WorkerFailureClassifier, WorkerFailureClass
            normal_stage = PlanningWorldPreparation.generation_stage
            normal_classify = WorkerFailureClassifier.classify
            old_stage_used = False
            old_classification_used = False
            def legacy_world_stage(*args, **kwargs):
                nonlocal old_stage_used
                stage = normal_stage(*args, **kwargs)
                if old_stage_used:
                    return stage
                old_stage_used = True
                schema = deepcopy(stage.output_schema)
                refs = schema["properties"]["candidates"]["items"]["properties"]["arc_refs"]
                refs.pop("maxItems", None)
                refs["items"].pop("enum", None)
                return PlanningProviderStage(stage.name, stage.task, schema)
            def legacy_world_classify(error):
                nonlocal old_classification_used
                if getattr(error, "code", "") == "WORLD_GENERATION_PLAN_REFERENCE_UNKNOWN" and not old_classification_used:
                    old_classification_used = True
                    return WorkerFailureClass.UNKNOWN_EXTERNAL_STATE
                return normal_classify(error)
            monkeypatch.setattr(PlanningWorldPreparation, "generation_stage", staticmethod(legacy_world_stage))
            monkeypatch.setattr(WorkerFailureClassifier, "classify", staticmethod(legacy_world_classify))
        normal_world_planning = transport.planning
        damaged_world_transition = 0
        def invalid_world_payload_once(stage, inputs):
            nonlocal damaged_world_transition
            result = normal_world_planning(stage, inputs)
            if stage == "world_candidates.generate":
                task = inputs["world_preparation"]
                assert task["transition_contract"]["payload_schema"]["properties"]["story_time"]["type"] == "object"
                if damaged_world_transition < (2 if stage_repair_recovery else 1) and result["candidates"]:
                    damaged_world_transition += 1
                    if world_result_repair == "reference-checkpoint":
                        result["candidates"][0]["arc_refs"] = ["unknown:arc"]
                    else:
                        transition = json.loads(result["candidates"][0]["transition"]["payload_json"])
                        transition["story_time"] = "chapter:1:morning"
                        result["candidates"][0]["transition"]["payload_json"] = json.dumps(transition)
                else:
                    assert task["result_repair"]["diagnostic"]["error_code"] == (
                        "WORLD_GENERATION_PLAN_REFERENCE_UNKNOWN" if world_result_repair == "reference-checkpoint"
                        else "WORLD_PROVIDER_TRANSITION_INVALID")
            return result
        transport.planning = invalid_world_payload_once
    if semantic_repair:
        normal_group_planning = transport.planning
        damaged_group = 0

        def invalid_cause_once(stage, inputs):
            nonlocal damaged_group
            result = normal_group_planning(stage, inputs)
            if stage == "chapter_group_plan.generate" and damaged_group < (2 if input_order_continuation else 1):
                damaged_group += 1
                result["narrative_event_chain"][0]["causes"] = ["absent-causal-event"]
            return result

        transport.planning = invalid_cause_once
    if input_order_continuation:
        from novel_forge.modules.story_planning_runtime import application as planning_module
        from novel_forge.modules.story_planning_runtime import planning_repair_routing as routing_module
        original_record = planning_module.StoryPlanningGenerationApplication._record_generation
        original_replay = planning_module._replay_generation_input_snapshot
        original_evidence = routing_module.native_planning_repair
        from novel_forge.modules.production_execution.routing_runtime import PostgresRoutingRegistry
        original_receipt = PostgresRoutingRegistry.planning_repair_receipt
        old_failure_injected = False

        def historical_unordered_record(app, *, operation_id, command, inputs):
            if command.repair_number == 2 and not command.runtime_continuation_id:
                with monkeypatch.context() as old:
                    old.setattr(planning_module, "_replay_generation_input_snapshot",
                        lambda *args: list(reversed(original_replay(*args))))
                    return original_record(app, operation_id=operation_id, command=command, inputs=inputs)
            return original_record(app, operation_id=operation_id, command=command, inputs=inputs)

        def historical_exact_order_guard(registry_owner, **scope):
            nonlocal old_failure_injected
            with AuthorityUnitOfWork(registry_owner.database_url) as uow:
                uow.cursor.execute("SELECT repair_number,runtime_continuation_id FROM authority_story_planning_generation WHERE operation_id=%s", [scope["operation_id"]])
                current = uow.cursor.fetchone()
                if current == (2, None) and not old_failure_injected:
                    old_failure_injected = True
                    original_evidence(uow.cursor, **{key: scope[key] for key in (
                        "project_id", "book_id", "operation_id", "task_type", "lineage")},
                        evidence_version=routing_module.LEGACY_REPAIR_VERSION)
            return original_receipt(registry_owner, **scope)

        monkeypatch.setattr(planning_module.StoryPlanningGenerationApplication, "_record_generation", historical_unordered_record)
        monkeypatch.setattr(PostgresRoutingRegistry, "planning_repair_receipt", historical_exact_order_guard)
    if gateway_null_recovery:
        from novel_forge.modules.story_planning_runtime import execution as planning_execution
        from novel_forge.api import authority_dependencies as dependencies
        from novel_forge.modules.command_kernel.errors import KernelError
        original_schema = planning_execution.planning_provider_output_schema
        original_validation = dependencies.validate_production_structured_result
        historical_rejection = False
        null_planning = transport.planning
        def retained_null_field(stage, inputs):
            value = null_planning(stage,inputs)
            if stage == "chapter_plan.generate":
                value["local_contract_nullable_probe"] = None
            return value
        transport.planning = retained_null_field
        def literal_null_schema(*args, **kwargs):
            schema = original_schema(*args, **kwargs)
            if "scene_plan" in schema.get("properties", {}):
                schema["properties"]["local_contract_nullable_probe"] = {"type":"null"}
                schema["required"].append("local_contract_nullable_probe")
            return schema
        def historical_null_validator(stage, schema, value, *, output_schema_ref=""):
            nonlocal historical_rejection
            if stage == "chapter_plan.generate" and not historical_rejection:
                historical_rejection = True
                from novel_forge.modules.story_planning_runtime.gateway_result_recovery import literal_null_paths
                assert literal_null_paths(schema,value)
                raise KernelError("CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID", "$.local_contract_nullable_probe uses unsupported schema type null")
            return original_validation(stage, schema, value, output_schema_ref=output_schema_ref)
        monkeypatch.setattr(planning_execution,"planning_provider_output_schema",literal_null_schema)
        monkeypatch.setattr(dependencies,"validate_production_structured_result",historical_null_validator)
    if stage_repair_recovery:
        known_planning=transport.planning
        damaged_knowledge=False
        def invalid_knowledge_once(stage,inputs):
            nonlocal damaged_knowledge
            value=known_planning(stage,inputs)
            if stage=='chapter_plan.generate' and not damaged_knowledge:
                damaged_knowledge=True
                value['character_participation'][0]['known_fact_ids']=['unknown:fact']
            return value
        transport.planning=invalid_knowledge_once
    if scene_core_recovery or scene_information_recovery:
        original_scene_planning = transport.planning
        def selected_specialisms_only(stage, inputs):
            value = original_scene_planning(stage, inputs)
            if stage == 'chapter_plan.generate':
                for scene in value['scene_plan']:
                    scene['realization_capabilities'] = ['SKELETON','ACTION'] if scene_information_recovery else ['ACTION']
            return value
        transport.planning = selected_specialisms_only
    if scene_information_recovery:
        original_information_draft = transport.chapter
        information_call_count = 0
        def information_draft(stage, inputs):
            nonlocal information_call_count
            value = original_information_draft(stage, inputs)
            if stage == 'draft':
                information_call_count += 1
                if information_call_count == 1:
                    value['scene_artifacts'][0]['used_fact_ids'] = ['fact:hidden-cost']
                else:
                    assert inputs.get('candidate_repair', {}).get('source_effect_id')
                    if information_call_count == 2:
                        value['scene_artifacts'][0]['used_fact_ids'] = ['fact:undeclared']
                    else:
                        assert inputs['candidate_repair']['contract_version'] == 'chapter-candidate-output-repair.v1'
            return value
        class InformationDraftTransport:
            def __call__(self, stage, inputs):
                return information_draft(stage, inputs)
            def __getattr__(self, name):
                return getattr(original_information_draft, name)
        transport.chapter = InformationDraftTransport()
    if review_knowledge_recovery:
        original_review_transport = transport.chapter
        review_scope_calls = 0
        def scoped_review(stage, inputs):
            nonlocal review_scope_calls
            value = original_review_transport(stage, inputs)
            if stage == 'review':
                review_scope_calls += 1
                if review_scope_calls == 1:
                    value['knowledge_checks'].append({'knowledge_card_asset_version_id':'knowledge:not-delivered',
                        'status':'NOT_USED','reason':'retained incorrect catalog judgment','evidence':None,
                        'conditions_checked':[],'exceptions_checked':[],'issue_codes':[]})
                else:
                    assert inputs['candidate_repair']['contract_version'] == 'chapter-review-output-repair.v1'
                    assert inputs['candidate_repair']['diagnostic']['error_code'] == 'REVIEW_KNOWLEDGE_CHECK_INVALID'
                    assert inputs['review_knowledge_scope_contract'] == 'delivered-card-scope.v1'
            return value
        class ScopedReviewTransport:
            def __call__(self, stage, inputs):
                return scoped_review(stage, inputs)
            def __getattr__(self, name):
                return getattr(original_review_transport, name)
        transport.chapter = ScopedReviewTransport()
    if length_scope_recovery:
        original_length_transport = transport.chapter
        length_revision_calls = 0
        support_calls = 0
        def measured_length_response(stage, inputs):
            nonlocal length_revision_calls, support_calls
            value = original_length_transport(stage, inputs)
            if stage == 'draft':
                value['scene_artifacts'][0]['text'] += '甲'
            elif stage == 'review':
                value['issues'][0]['evidence'] = {'quote':inputs['draft']['scene_artifacts'][-1]['text']}
            elif stage == 'revision':
                length_revision_calls += 1
                value['scene_artifacts'][0]['text'] += '乙' if length_revision_calls == 2 else '乙丙丁'
                if length_revision_calls == 2:
                    assert inputs['candidate_repair']['contract_version'] == 'chapter-length-output-repair.v1'
                    assert inputs['chapter_length_repair_scope']['source_han_characters'] == 1
                elif length_revision_calls == 3:
                    assert inputs['candidate_repair']['contract_version'] == 'chapter-candidate-output-repair.v1'
                    assert inputs['candidate_repair']['diagnostic']['error_code'] == 'CHAPTER_LENGTH_REPAIR_INCOMPLETE'
                    assert inputs['candidate_repair']['length_observation']['observed'] == 2
                    assert '2' in inputs['candidate_repair']['diagnostic']['error_message']
            if stage == 'canon_support':
                support_calls += 1
                if support_calls == 1:
                    for claim in value['claims']:
                        claim['observed_kind']='DOCUMENT_CONTENT'
                else:
                    assert inputs['support_kind_contract']=='canon-support-kinds.v2'
            if stage in {'draft','revision'}:
                from novel_forge.modules.chapter_authority.realization_composition import serialize_realization
                value['text'] = serialize_realization(value['scene_artifacts'])
            return value
        class MeasuredLengthTransport:
            def __call__(self, stage, inputs):
                return measured_length_response(stage, inputs)
            def __getattr__(self, name):
                return getattr(original_length_transport, name)
        transport.chapter = MeasuredLengthTransport()
    registry.register(transport)
    if creative_validation:
        from tests.integration.creative_validation_production_support import controlled_member_environment
        env = controlled_member_environment(tmp_path, env, monkeypatch, transport)
        if memo_timeout_recovery:
            from novel_forge.modules.chapter_authority.execution_gateway import PostgresProductionExecutionPayloadResolver
            from novel_forge.modules.production_execution.process_supervisor import CodexProcessSupervisor, ProcessTimeout, PersistentExecutionDirectory
            import hashlib
            executable=Path(env['NOVEL_FORGE_CODEX_EXECUTABLE'])
            script=executable.read_text().replace('import json,pathlib,sys','import json,pathlib,sys,time').replace(
                ' target.write_bytes(', ' if target.with_name("memo-timeout-fixture").exists(): time.sleep(1000)\n target.write_bytes(')
            executable.write_text(script)
            env['NOVEL_FORGE_CODEX_EXECUTABLE_SHA256']='sha256:'+hashlib.sha256(executable.read_bytes()).hexdigest()
            normal_resolve=PostgresProductionExecutionPayloadResolver.resolve
            normal_run=CodexProcessSupervisor.run
            delayed=0
            def delayed_memo(resolver,request,admission):
                nonlocal delayed
                payload=normal_resolve(resolver,request,admission)
                if request.stage=='memo' and delayed < (2 if memo_timeout_prefix_recovery else 1):
                    delayed += 1
                    layout=PersistentExecutionDirectory(env['NOVEL_FORGE_CODEX_EXECUTION_ROOT']).prepare(request.execution_id)
                    layout.result_path('memo-timeout-fixture').write_text('controlled timeout; no real Provider')
                return payload
            def short_controlled_timeout(supervisor,request,**kwargs):
                layout=supervisor.execution_directory.prepare(request.execution_id)
                if layout.result_path('memo-timeout-fixture').exists():
                    request=replace(request,timeout=ProcessTimeout(0.05,poll_interval_seconds=0.01,termination_grace_seconds=1))
                return normal_run(supervisor,request,**kwargs)
            monkeypatch.setattr(PostgresProductionExecutionPayloadResolver,'resolve',delayed_memo)
            monkeypatch.setattr(CodexProcessSupervisor,'run',short_controlled_timeout)
        settings = replace(settings, environment="validation", root=Path(__file__).resolve().parents[2])
    execution = build_production_execution_composition(
        settings,
        env=env,
        provider_registry=registry,
        planning_fixture_factory=transport.planning,
        chapter_fixture_factory=transport.chapter,
    )
    try:
        chapter = build_chapter_authority_application(
            settings, execution=execution, env=env
        )
        composition = build_book_production_composition(
            settings,
            principal=principal,
            execution=execution,
            chapter_application=chapter,
            env=env,
        )
        formation = composition.formation
        assert formation is not None
        formation_worker = TrustedPrincipalResolver(
            environment="test",
            configured_project_scope=frozenset({harness.project_id}),
        ).resolve_book_formation_worker_principal("synthesis-worker")
        formation_key = f"{harness.project_id}:synthesis:formation"
        formation_run_id = deterministic_story_formation_run_id(
            project_id=harness.project_id,
            book_id=harness.book_ids[0],
            stable_idempotency_key=formation_key,
        )
        # COMPATIBILITY: This successor proves the original v2-to-v3 capacity upgrade, with its frozen input policy.
        capacity_policy_path = "tests/fixtures/creation/frozen-capacity-policy-6b69b22.json" if capacity_policy_upgrade else "config/execution_templates/creation_inputs.json"
        capacity_profiles = json.loads((Path(__file__).resolve().parents[2] / capacity_policy_path).read_text())
        capacity_profiles["profiles"]["production_profile"]["content"]["language_contract"] = {"required_language": "zh-CN"}
        admitted = formation.admit(
            StartStoryFormationCommand(
                project_id=harness.project_id,
                workspace_id=harness.workspace_id,
                book_id=harness.book_ids[0],
                actor_id=principal.principal_id,
                expected_book_version=1,
                stable_idempotency_key=formation_key,
                trace_id="trace:synthesis-formation",
                correlation_id=harness.project_id,
                frozen_input=StoryFormationInput(
                    creative_brief_asset_version_id=brief.asset_version_id,
                    creative_brief_content_hash=brief.content_hash,
                    generation_policy={
                        "contract_version": "formation-generation.v5" if capacity_policy_upgrade else "formation-generation.v2",
                        **({"creative_selection": "AUTHOR_COMPARISON", "creation_input_policy": capacity_profiles} if capacity_policy_upgrade else {}),
                        "approval_mode": "REVIEW_PLAN" if manual_review else "AUTO",
                        "creative_candidates": 2,
                        "target_chapters": target_chapters,
                        "title": "Witness Map",
                        **({} if manual_review else {"auto_authorization": {
                            "contract_version": "formation-auto-authorization.v1",
                            "policy_version": "formation-auto-policy.v1",
                            "authorization_ref": "test:synthesis-formation",
                            "authorized_by_principal_id": principal.principal_id,
                            "project_id": harness.project_id,
                            "workspace_id": harness.workspace_id,
                            "book_id": harness.book_ids[0],
                            "formation_run_id": formation_run_id,
                            "allowed_actions": [
                                "book_design.candidate.activate",
                                "book_design.candidate.decide",
                                "story_planning.candidate.activate",
                                "story_planning.candidate.approve",
                            ],
                        }}),
                    },
                ),
            ),
            principal=principal,
        )
        projection_checkpoints = []
        recovered_activation = False

        def fail_activation(checkpoint):
            if checkpoint == "after_business_projection_update":
                projection_checkpoints.append(checkpoint)
                if len(projection_checkpoints) == 3:
                    raise RuntimeError("simulated activation projection crash")

        formation.generation.book_design.fault_injector = None if manual_review else fail_activation
        evaluation_failed = False
        concurrent_recovery_heads = []
        if evaluation_recovery:
            from novel_forge.modules.story_design_authority.evaluation_runtime import NarrativeSemanticEvaluationHandler, NarrativeSemanticEvaluationApplication
            original_evaluation = NarrativeSemanticEvaluationHandler.execute
            original_admission = NarrativeSemanticEvaluationApplication._admit_candidate_once

            def fail_evaluation_preflight_once(handler, request):
                nonlocal evaluation_failed
                if request.command["payload"]["generator_operation_name"] == "book_design.propose" and not evaluation_failed:
                    from novel_forge.modules.command_kernel.errors import KernelError
                    evaluation_failed = True
                    raise KernelError("NARRATIVE_EVALUATION_PROVIDER_CONTEXT_INVALID", "retained preflight failure before any Effect")
                return original_evaluation(handler, request)

            monkeypatch.setattr(NarrativeSemanticEvaluationHandler, "execute", fail_evaluation_preflight_once)

            def admit_concurrently_once(application, command, admission_command):
                if evaluation_failed and not concurrent_recovery_heads and command.generator_operation_name == "book_design.propose":
                    from concurrent.futures import ThreadPoolExecutor
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        concurrent_recovery_heads.extend(pool.map(lambda _: original_admission(application, command, admission_command), range(2)))
                    return concurrent_recovery_heads[0]
                return original_admission(application, command, admission_command)

            monkeypatch.setattr(NarrativeSemanticEvaluationApplication, "_admit_candidate_once", admit_concurrently_once)
        runtime_recovered = False
        capacity_failed = False
        if capacity_continuation:
            resolver = formation.generation.planning.execution_binder.resolver.execution_preparer
            original_context = resolver._context_bundle
            def fail_capacity_once(**kwargs):
                nonlocal capacity_failed
                if kwargs["command"].repair_of_operation_id and not capacity_failed:
                    from novel_forge.modules.command_kernel.errors import KernelError
                    capacity_failed = True
                    if capacity_policy_upgrade:
                        original_context(**kwargs)
                    raise KernelError("PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED", "retained zero-dispatch capacity failure")
                return original_context(**kwargs)
            resolver._context_bundle = fail_capacity_once
        if runtime_recovery:
            preparer = formation.generation.planning.execution_binder.resolver.execution_preparer
            def profile_collision(**_):
                from novel_forge.modules.command_kernel.errors import KernelError
                raise KernelError("EXECUTION_CONTRACT_FROZEN_CONFLICT", "retained legacy schema conflicts before dispatch")
            preparer._execution_binding = profile_collision
        selected_creative = ""
        for _ in range(24 if manual_review else 12):
            formation.schedule_candidates(
                limit=1,
                project_id=harness.project_id,
                formation_run_id=admitted.formation_run_id,
            )
            claim = formation.runtime_jobs.claim(
                runtime_group="story_formation",
                worker_id="synthesis-worker",
                lease_seconds=60,
                job_kinds=("STORY_FORMATION_ADVANCE",),
                project_id=harness.project_id,
            )
            if claim is None:
                break
            try:
                execute_story_formation_claim(
                    formation.runtime_jobs,
                    formation,
                    formation_worker,
                    claim,
                    lease_seconds=60,
                )
            except Exception as exc:
                from novel_forge.modules.command_kernel.errors import KernelError
                if foundation_uncertainty_recovery and isinstance(exc, KernelError) and exc.code == "FOUNDATION_APPLICABILITY_UNRESOLVED":
                    assert legacy_candidate is None
                    with AuthorityUnitOfWork(DATABASE_URL) as uow:
                        uow.cursor.execute("SELECT g.operation_id,g.candidate_asset_version_id,v.content_hash FROM authority_story_planning_generation g JOIN authority_asset_version v ON v.asset_version_id=g.candidate_asset_version_id WHERE g.project_id=%s AND g.generator_operation_name='world.design.generate'", [harness.project_id])
                        legacy_candidate = uow.cursor.fetchone()
                    monkeypatch.setattr(planning_module, "require_resolved_foundation_applicability", resolved_check)
                    current = formation.require(admitted.formation_run_id)
                    formation.resume(admitted.formation_run_id, expected_version=current["version"], principal=principal)
                    continue
                if capacity_continuation and isinstance(exc, KernelError) and exc.code in {"PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED", "PLANNING_RUNTIME_CONTINUATION_OWNER_REQUIRED"}:
                    execution.close()
                    formation, execution, chapter, composition = _recover_capacity_formation(harness=harness,
                        chapter_pack=chapter_pack, principal=principal, pack_actor=template_actor, settings=settings, env=env, registry=registry,
                        transport=transport, admitted=admitted, monkeypatch=monkeypatch, policy_upgrade=capacity_policy_upgrade)
                    formation.generation.book_design.fault_injector = fail_activation
                    continue
                if valid_result_admission and isinstance(exc, KernelError) and exc.code == "PLANNING_RESULT_REPAIR_BOUND_EXCEEDED":
                    from concurrent.futures import ThreadPoolExecutor
                    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
                    planning = formation.generation.planning
                    failures = AuthorityAssetQuery(DATABASE_URL).list_versions(project_id=harness.project_id, asset_type="planning_generation_result_failure")
                    assert len(failures) == 1
                    failure = failures[0]
                    source = failure.content["operation_id"]
                    before = len(transport.calls)
                    def register(actor=principal):
                        return planning.register_result_admission_recovery(source,project_id=harness.project_id,
                            source_asset_version_id=failure.asset_version_id,reason="compatible parser repair; retain original result",principal=actor)
                    with pytest.raises(PermissionError):
                        register(formation_worker)
                    from novel_forge.modules.story_planning_runtime import result_admission
                    with monkeypatch.context() as strict:
                        verified = result_admission.verify_template_provenance
                        strict.setattr(result_admission,"verify_template_provenance",lambda *args: {**verified(*args),"mode":"STRICT_PRODUCTION"})
                        with pytest.raises(KernelError,match="PLANNING_RESULT_ADMISSION_POLICY_REQUIRED"):
                            register()
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        recoveries = list(pool.map(lambda _:register(), range(2)))
                    assert len({r["asset_version_id"] for r in recoveries}) == 1
                    assert register()["replayed"] and len(transport.calls) == before
                    with AuthorityUnitOfWork(DATABASE_URL) as uow:
                        uow.cursor.execute("SELECT status FROM authority_operation WHERE operation_id=%s",[source])
                        assert uow.cursor.fetchone()[0] == "FAILED_FINAL"
                        uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE operation_id=%s",[recoveries[0]["operation_id"]])
                        assert uow.cursor.fetchone()[0] == 0
                    failed = formation.require(admitted.formation_run_id)
                    formation.resume(admitted.formation_run_id,expected_version=failed["version"],principal=principal)
                    continue
                if evaluation_recovery and isinstance(exc, KernelError) and exc.code == "NARRATIVE_EVALUATION_PROVIDER_CONTEXT_INVALID":
                    failed = formation.require(admitted.formation_run_id)
                    assert failed["lifecycle"] == "FAILED"
                    formation.resume(admitted.formation_run_id, expected_version=failed["version"], principal=principal)
                    continue
                if isinstance(exc, KernelError) and exc.code == "EXECUTION_CONTRACT_FROZEN_CONFLICT" and runtime_recovery and not runtime_recovered:
                    historical.undo()
                    historical = None
                    execution.close()
                    formation, execution = _recover_runtime_profile_formation(
                        harness=harness, chapter_pack=chapter_pack, formation=formation,
                        principal=principal, settings=settings, env=env, registry=registry,
                        transport=transport, admitted=admitted,
                    )
                    formation.generation.book_design.fault_injector = fail_activation
                    runtime_recovered = True
                    continue
                assert (
                    str(exc) == "simulated activation projection crash"
                    and not recovered_activation
                )
                from novel_forge.modules.book_design_authority.query import (
                    BookDesignAuthorityQuery,
                )
                from novel_forge.storage.authority_asset_store import (
                    AuthorityAssetQuery,
                )

                assert not BookDesignAuthorityQuery(DATABASE_URL).require_book(
                    project_id=harness.project_id, book_id=harness.book_ids[0]
                )["active_book_design_version_id"]
                assert not AuthorityAssetQuery(DATABASE_URL).list(
                    project_id=harness.project_id, asset_type="character_arc_portfolio"
                )
                calls_before_recovery = len(transport.calls)
                execution.close()
                execution = build_production_execution_composition(
                    settings,
                    env=env,
                    provider_registry=registry,
                    planning_fixture_factory=transport.planning,
                    chapter_fixture_factory=transport.chapter,
                )
                chapter = build_chapter_authority_application(
                    settings, execution=execution, env=env
                )
                composition = build_book_production_composition(
                    settings,
                    principal=principal,
                    execution=execution,
                    chapter_application=chapter,
                    env=env,
                )
                formation = composition.formation
                failed = formation.require(admitted.formation_run_id)
                formation.resume(
                    admitted.formation_run_id,
                    expected_version=failed["version"],
                    principal=principal,
                )
                recovered_activation = True

            waiting = formation.require(admitted.formation_run_id)
            if (manual_review or capacity_policy_upgrade) and waiting["lifecycle"] == "WAITING_APPROVAL":
                from novel_forge.modules.command_kernel.errors import KernelError

                reviewer = replace(principal, permissions=principal.permissions | {"book.authority.query"})
                review = formation.review_candidates(admitted.formation_run_id, principal=reviewer)
                candidates = review["candidates"]
                target = candidates[1] if len(candidates) > 1 else candidates[0]
                if len(candidates) > 1:
                    with pytest.raises(KernelError, match="outside the frozen comparison"):
                        formation.author_decision(
                            admitted.formation_run_id, expected_version=review["version"],
                            candidate_asset_version_id=brief.asset_version_id,
                            candidate_content_hash=brief.content_hash, decision="SELECT",
                            reason="Invalid cross-role selection must not change the comparison",
                            idempotency_key="manual:outside-candidate-set", principal=reviewer,
                        )
                    assert formation.require(admitted.formation_run_id)["version"] == review["version"]
                    rejected = formation.author_decision(
                        admitted.formation_run_id, expected_version=review["version"],
                        candidate_asset_version_id=candidates[0]["asset_version_id"],
                        candidate_content_hash=candidates[0]["content_hash"],
                        decision="REJECT", reason="Fixture author rejects first branch; preserve alternatives",
                        idempotency_key="manual:reject-first", principal=reviewer,
                    )
                    with pytest.raises(KernelError, match="Select and approve"):
                        formation.resume(admitted.formation_run_id, expected_version=rejected["version"], principal=reviewer)
                    review = rejected
                    selected_creative = target["asset_version_id"]
                args = dict(expected_version=review["version"],
                            candidate_asset_version_id=target["asset_version_id"],
                            candidate_content_hash=target["content_hash"], decision="APPROVE",
                            reason="Fixture author preserves witness conflict and selects this exact branch",
                            idempotency_key=f"manual:approve:{waiting['current_stage']}", principal=reviewer)
                approved = formation.author_decision(admitted.formation_run_id, **args)
                repeated = formation.author_decision(admitted.formation_run_id, **args)
                assert repeated["version"] == approved["version"]
                assert repeated["recovery_instruction"]["candidate_asset_version_id"] == target["asset_version_id"]
                formation.resume(admitted.formation_run_id, expected_version=approved["version"], principal=reviewer)

            if formation.require(admitted.formation_run_id)["lifecycle"] == "READY":
                break
        result = formation.require(admitted.formation_run_id)
        assert result["lifecycle"] == "READY", result
        if capacity_policy_upgrade:
            from novel_forge.modules.story_planning_runtime.runtime_continuation import capacity_upgrade_projection_hash
            from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT successor_operation_id,target_runtime->'planning_capacity' FROM authority_story_planning_runtime_continuation WHERE project_id=%s", [harness.project_id])
                successor_id, allocation = uow.cursor.fetchone()
            context = AuthorityAssetQuery(DATABASE_URL).require(project_id=harness.project_id,
                logical_ref=f"planning/context_bundles/{successor_id}.json")
            assert context.content["planning_context_policy_version"] == "context-policy:chapter-generation-pack:v3"
            assert allocation["projection_hash_policy"] == "capacity-upgrade-semantic-owner.v1"
            assert capacity_upgrade_projection_hash(context) == allocation["projection_hash"]
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT candidate_asset_version_id FROM authority_story_planning_generation WHERE operation_id=%s", [successor_id])
                assert uow.cursor.fetchone()[0]
            return
        if manual_review:
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT asset_version_id FROM authority_book_foundation_binding WHERE formation_run_id=%s AND foundation_role='CREATIVE_FOUNDATION' AND freshness='CURRENT'", [admitted.formation_run_id])
                assert str(uow.cursor.fetchone()[0]) == selected_creative
                uow.cursor.execute("SELECT operation.input_asset_snapshot FROM authority_story_planning_generation generation JOIN authority_operation operation ON operation.operation_id=generation.operation_id WHERE generation.project_id=%s AND generation.generator_operation_name='theme.candidates.generate'", [harness.project_id])
                parents = uow.cursor.fetchall()
                assert parents and all(any(item["asset_version_id"] == selected_creative for item in row[0]) for row in parents)
                uow.cursor.execute("SELECT checkpoint->'author_decisions' FROM authority_story_formation_stage WHERE formation_run_id=%s AND stage='CREATIVE_SEARCH'", [admitted.formation_run_id])
                decisions = uow.cursor.fetchone()[0]
                assert [item["decision"] for item in decisions] == ["REJECT", "APPROVE"]
            return
        if evaluation_recovery:
            assert evaluation_failed
            assert len(concurrent_recovery_heads) == 2
            assert len({head["operation_id"] for head in concurrent_recovery_heads}) == 1
            assert {head["generation"] for head in concurrent_recovery_heads} == {2}
            with AuthorityUnitOfWork(DATABASE_URL) as recovery_uow:
                recovery_uow.cursor.execute("""
                    SELECT source.status,successor.status,source.command_payload=successor.command_payload,
                           successor.causation_operation_id=source.operation_id,recovery.candidate_asset_version_id,
                           source_execution.candidate_asset_version_id,successor_execution.candidate_asset_version_id,
                           source_execution.lifecycle,successor_execution.lifecycle,
                           (SELECT count(*) FROM authority_external_effect WHERE operation_id=source.operation_id)
                    FROM authority_narrative_formation_recovery recovery
                    JOIN authority_operation source ON source.operation_id=recovery.source_operation_id
                    JOIN authority_operation successor ON successor.operation_id=recovery.successor_operation_id
                    JOIN authority_narrative_evaluation_execution source_execution ON source_execution.operation_id=source.operation_id
                    JOIN authority_narrative_evaluation_execution successor_execution ON successor_execution.operation_id=successor.operation_id
                    WHERE recovery.project_id=%s
                """, [harness.project_id])
                continuations = recovery_uow.cursor.fetchall()
            assert len(continuations) == 1
            recovery = continuations[0]
            assert recovery[:4] == ("FAILED_FINAL", "SUCCEEDED", True, True)
            assert recovery[4] == recovery[5] == recovery[6]
            assert recovery[7:] == ("FAILED", "SUCCEEDED", 0)
            with AuthorityUnitOfWork(DATABASE_URL) as recovery_uow:
                recovery_uow.cursor.execute("SELECT authority_narrative_formation_gate_is_open(successor_operation_id,project_id,recovery_id) FROM authority_narrative_formation_recovery WHERE project_id=%s", [harness.project_id])
                assert recovery_uow.cursor.fetchone()[0] is False
        assert runtime_recovered is runtime_recovery
        if runtime_recovery:
            _assert_runtime_continuation_once(formation, harness, transport, principal)
        creative_candidates = [
            item
            for item in AuthorityAssetQuery(DATABASE_URL).list_versions(
                project_id=harness.project_id,
                asset_type="planning_generation_candidate",
            )
            if item.content.get("generator_operation_name")
            == "creative.candidates.generate"
        ]
        assert sorted(item.lifecycle for item in creative_candidates) == [
            "ACTIVE",
            "CANDIDATE",
        ]
        from novel_forge.modules.story_design_authority.evaluation_execution import (
            PostgresNarrativeEvaluationExecutionContractBinder,
        )

        asset_query = AuthorityAssetQuery(DATABASE_URL)
        book_design = next(
            item for item in asset_query.list_versions(
                project_id=harness.project_id, asset_type="book_design"
            ) if item.lifecycle == "ACTIVE"
        )
        if not creative_validation:
            binder = object.__new__(PostgresNarrativeEvaluationExecutionContractBinder)
            binder.evaluation_query = asset_query
            dependencies = binder._canonical_dependencies(
                book_design, book_id=harness.book_ids[0]
            )
            assert len(dependencies) == 6
            assert all(
                source.asset_type == "planning_generation_candidate"
                and source.content["book_id"] == harness.book_ids[0]
                and qualification.content["candidate_content_hash"] == source.content_hash
                for _, source, qualification in dependencies
            )
        assert (
            recovered_activation and len(transport.calls) == calls_before_recovery == (8 if result_repair or author_result_repair or foundation_uncertainty_recovery else 7)
        )
        if foundation_uncertainty_recovery:
            assert legacy_candidate is not None
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT o.status,v.content_hash,(SELECT count(*) FROM authority_story_planning_validation_report r WHERE r.candidate_asset_version_id=v.asset_version_id AND r.status='FAIL'),(SELECT count(*) FROM authority_book_foundation_binding b WHERE b.asset_version_id=v.asset_version_id) FROM authority_operation o JOIN authority_asset_version v ON v.asset_version_id=%s WHERE o.operation_id=%s", [legacy_candidate[1],legacy_candidate[0]])
                assert uow.cursor.fetchone() == ("SUCCEEDED", legacy_candidate[2], 1, 0)
                uow.cursor.execute("SELECT count(*) FROM authority_operation WHERE project_id=%s AND causation_operation_id=%s AND command_payload #>> '{payload,repair_of_candidate_id}'=%s", [harness.project_id,legacy_candidate[0],legacy_candidate[1]])
                assert uow.cursor.fetchone()[0] == 1
            return
        assert {call["stage"] for call in transport.calls} == {
            "creative.candidates.generate",
            "theme.candidates.generate",
            "ending.intent.generate",
            "reader.promise.generate",
            "world.design.generate",
            "character.cast.generate",
        }
        if result_repair:
            from novel_forge.modules.story_planning_runtime.application import _command_from_payload
            from concurrent.futures import ThreadPoolExecutor

            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT op.operation_id, op.status, op.command_payload->'payload', op.causation_operation_id, g.candidate_asset_version_id FROM authority_operation op JOIN authority_story_planning_generation g USING(operation_id) WHERE op.project_id=%s AND g.generator_operation_name='world.design.generate' ORDER BY op.created_at", [harness.project_id])
                generations = uow.cursor.fetchall()
            assert len(generations) == 2
            failed, repaired = generations
            assert failed[1] == "FAILED_FINAL" and not failed[4]
            assert repaired[1] == "SUCCEEDED" and repaired[4]
            assert str(repaired[3]) == str(failed[0])
            failures = AuthorityAssetQuery(DATABASE_URL).list_versions(project_id=harness.project_id, asset_type="planning_generation_result_failure")
            assert len(failures) == 1 and failures[0].eligibility == "INELIGIBLE"
            assert failures[0].content["candidate_status"] == "NOT_MATERIALIZED"
            assert failures[0].content["diagnostic"]["error_code"] == "WORLD_FOUNDATION_SCHEMA_INVALID"
            from novel_forge.modules.command_kernel.errors import KernelError
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                frozen_failure = [{"asset_version_id": failures[0].asset_version_id, "content_hash": failures[0].content_hash}]
                with pytest.raises(KernelError, match="AUTHORITY_INPUT_NOT_ELIGIBLE"):
                    uow.repositories.chapter_authority.frozen_inputs(harness.project_id, frozen_failure)
                readable_failure = uow.repositories.chapter_authority.frozen_inputs(harness.project_id, frozen_failure, repair_result_asset_version_id=failures[0].asset_version_id)
                assert readable_failure[0]["asset_type"] == "planning_generation_result_failure"
            before = len(transport.calls)
            planning = formation.generation.planning
            original = _command_from_payload(dict(failed[2]))
            from novel_forge.modules.story_planning_runtime.result_recovery import require_result_repair_source
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT output.asset_version_id FROM authority_operation_output_asset output JOIN authority_asset asset USING(asset_id) WHERE output.operation_id=%s AND asset.asset_type='model_call_log'", [failed[0]])
                legacy_result_asset = str(uow.cursor.fetchone()[0])
            retained = require_result_repair_source(DATABASE_URL, command=original, operation_id=str(failed[0]), source_asset_version_id=legacy_result_asset)
            assert retained["diagnostic"] == failures[0].content["diagnostic"]
            assert retained["raw_result"] == failures[0].content["raw_result"]
            with pytest.raises(KernelError, match="PLANNING_RESULT_REPAIR_INPUT_DRIFT"):
                require_result_repair_source(DATABASE_URL, command=replace(original, auto_approve_low_risk=True), operation_id=str(failed[0]))
            with ThreadPoolExecutor(max_workers=2) as pool:
                replayed = list(pool.map(lambda _: planning.generate(original, principal=formation_worker), range(2)))
            assert {item.candidate_asset_version_id for item in replayed} == {str(repaired[4])}
            assert len(transport.calls) == before
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT status FROM authority_operation WHERE operation_id=%s", [failed[0]])
                assert uow.cursor.fetchone()[0] == "FAILED_FINAL"
                uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE operation_id IN (%s,%s)", [failed[0], repaired[0]])
                assert uow.cursor.fetchone()[0] == 2
            if not complete_after_result_repair:
                return
        if author_result_repair and not capacity_continuation:
            from novel_forge.modules.story_planning_runtime.application import _command_from_payload
            from novel_forge.modules.story_planning_runtime.result_recovery import require_result_repair_source
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT op.operation_id,op.status,op.command_payload->'payload',op.causation_operation_id,g.candidate_asset_version_id FROM authority_operation op JOIN authority_story_planning_generation g USING(operation_id) WHERE op.project_id=%s AND g.generator_operation_name='reader.promise.generate' ORDER BY op.created_at", [harness.project_id])
                failed, repaired = uow.cursor.fetchall()
                uow.cursor.execute("SELECT output.asset_version_id FROM authority_operation_output_asset output JOIN authority_asset asset USING(asset_id) WHERE output.operation_id=%s AND asset.asset_type='model_call_log'", [failed[0]])
                legacy_result_asset = str(uow.cursor.fetchone()[0])
            assert failed[1] == "FAILED_FINAL" and not failed[4]
            assert repaired[1] == "SUCCEEDED" and repaired[3] == failed[0]
            failures = asset_query.list_versions(project_id=harness.project_id, asset_type="planning_generation_result_failure")
            assert len(failures) == 1 and failures[0].eligibility == "INELIGIBLE"
            assert failures[0].content["diagnostic"]["error_code"] == "AUTHOR_DESIGN_INPUT_INVALID"
            original = _command_from_payload(dict(failed[2]))
            retained = require_result_repair_source(DATABASE_URL, command=original, operation_id=str(failed[0]), source_asset_version_id=legacy_result_asset)
            assert retained["diagnostic"] == failures[0].content["diagnostic"]
            before = len(transport.calls)
            replayed = formation.generation.planning.generate(original, principal=formation_worker)
            assert replayed.candidate_asset_version_id == str(repaired[4])
            assert len(transport.calls) == before
            return
        from novel_forge.modules.book_authority.creation_inputs import (
            prepare_creation_inputs,
        )
        from novel_forge.modules.book_authority.opening import (
            OpenBookProductionRequest,
            _OPENING_INPUT_ROLES,
        )
        from novel_forge.modules.runtime_job import RuntimeJobAuthority
        from novel_forge.workers.book_authority import execute_book_opening_claim

        policy = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "tests/fixtures/creation/short-arc/creation.json"
            ).read_text()
        )
        if length_scope_recovery:
            for fact in policy["profiles"]["platform_profile"]["content"]["structured_facts"]:
                if fact["key"] == "platform_rules":
                    fact["value"]["chapter_length"] = {"unit":"HAN_CHARACTERS_V1","minimum":3,"maximum":4}
        policy["profiles"]["production_profile"]["content"].update(fixture_production_profile)
        policy["profiles"]["production_profile"]["content"]["target_chapter_count"] = target_chapters
        if creative_validation:
            from novel_forge.modules.book_authority.creation_runtime import continue_creation
            from novel_forge.modules.authority_security import PrincipalType
            from types import SimpleNamespace
            import time

            worker = replace(principal, principal_type=PrincipalType.WORKER,
                principal_id="creation-book" if stage_repair_recovery else principal.principal_id,
                permissions=principal.permissions - {"book.authority.approve_replan"})
            if completed_release_recovery:
                from novel_forge.modules.command_kernel.errors import KernelError
                from novel_forge.modules.story_planning_runtime.application import _command_from_payload
                from novel_forge.modules.story_planning_runtime.gateway_result_recovery import recover, RETRYABLE_RELEASE_VERSION
                planning = composition.planning
                execute = planning.execution_binder.execute
                retained = {}
                def fail_completed_assembly(**values):
                    candidate = execute(**values)
                    if values["command"].generator_operation_name == "book_plan.generate" and not retained:
                        retained["operation_id"] = values["operation_id"]
                        raise KernelError("CAPABILITY_PACK_RUNTIME_ADMISSION_DRIFT", "runtime contract differs from Pack execution snapshot: release_sha")
                    return candidate
                monkeypatch.setattr(planning.execution_binder, "execute", fail_completed_assembly)
                continue_creation(composition=composition, content=content, chapter=chapter,
                    formation_run_id=admitted.formation_run_id, formation_worker=formation_worker,
                    book_worker=worker, maximum_ticks=80, deadline=time.monotonic() + 240, creation_policy=policy)
                assert retained
                source_id = retained["operation_id"]
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT status,command_payload->'payload' FROM authority_operation WHERE operation_id=%s", [source_id])
                    status, payload = uow.cursor.fetchone()
                    assert status == "FAILED_RETRYABLE"
                    uow.cursor.execute("SELECT to_jsonb(attempt) FROM authority_attempt attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1", [source_id])
                    failed = uow.cursor.fetchone()[0]
                command = _command_from_payload(payload)
                before = len(transport.calls), len(transport.chapter.calls)
                with pytest.raises(KernelError, match="PLANNING_GATEWAY_RESULT_RELEASE_DRIFT_INVALID"):
                    recover(planning, command=command, operation_id=source_id, principal=principal)
                planning.commit_sha = "e" * 40 if planning.commit_sha != "e" * 40 else "f" * 40
                monkeypatch.setattr(planning.execution_binder, "execute", execute)
                if completed_release_recovery == "cancel-race":
                    from concurrent.futures import ThreadPoolExecutor
                    from threading import Event
                    from novel_forge.storage.story_formation_repositories import StoryFormationRepository
                    cancelling, commit_cancel = Event(), Event()
                    cancel = StoryFormationRepository.cancel_continuation
                    def retained_cancel(repository, *args, **kwargs):
                        result = cancel(repository, *args, **kwargs)
                        retained["cancel_pid"] = repository.cursor.connection.info.backend_pid
                        cancelling.set()
                        assert commit_cancel.wait(10)
                        return result
                    monkeypatch.setattr(StoryFormationRepository, "cancel_continuation", retained_cancel)
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        cancelled = pool.submit(formation.cancel_continuation, admitted.formation_run_id,
                            principal=principal, reason="Native cancellation wins the result-recovery race", idempotency_key="cancel-release-recovery")
                        assert cancelling.wait(10)
                        recovered = pool.submit(recover, planning, command=command, operation_id=source_id, principal=principal)
                        blocked = False
                        try:
                            for _ in range(100):
                                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                                    uow.cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND %s=ANY(pg_blocking_pids(pid)))", [retained["cancel_pid"]])
                                    blocked = uow.cursor.fetchone()[0]
                                if blocked:
                                    break
                                time.sleep(.02)
                        finally:
                            commit_cancel.set()
                        assert blocked
                        cancelled.result(10)
                        with pytest.raises(KernelError, match="PLANNING_GATEWAY_RESULT_SUCCESSION_CONFLICT"):
                            recovered.result(10)
                    assert (len(transport.calls), len(transport.chapter.calls)) == before
                    with AuthorityUnitOfWork(DATABASE_URL) as uow:
                        uow.cursor.execute("SELECT candidate_asset_version_id FROM authority_story_planning_generation WHERE operation_id=%s", [source_id])
                        assert uow.cursor.fetchone()[0] is None
                    return
                if completed_release_recovery == "scan":
                    from novel_forge.modules.story_planning_runtime.gateway_result_recovery import recover_completed_planning_outputs
                    assert recover_completed_planning_outputs(planning, project_id=harness.project_id, book_id=command.book_id, principal=principal)
                    assert (len(transport.calls), len(transport.chapter.calls)) == before
                resumed = planning.generate(command, principal=principal)
                assert resumed.candidate_asset_version_id
                after = len(transport.calls), len(transport.chapter.calls)
                repeated = planning.generate(command, principal=principal)
                assert repeated.candidate_asset_version_id == resumed.candidate_asset_version_id
                assert (len(transport.calls), len(transport.chapter.calls)) == after
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT status FROM authority_operation WHERE operation_id=%s", [source_id])
                    assert uow.cursor.fetchone()[0] == "FAILED_RETRYABLE"
                    uow.cursor.execute("SELECT to_jsonb(attempt) FROM authority_attempt attempt WHERE attempt_id=%s", [failed["attempt_id"]])
                    assert uow.cursor.fetchone()[0] == failed
                    uow.cursor.execute("SELECT evidence,recovery.status FROM authority_planning_result_admission admission JOIN authority_operation recovery ON recovery.operation_id=admission.recovery_operation_id WHERE source_operation_id=%s", [source_id])
                    proof, recovery_status = uow.cursor.fetchone()
                    assert recovery_status == "SUCCEEDED" and proof["provider_invoked"] is False
                    assert proof["contract_version"] == RETRYABLE_RELEASE_VERSION
                    assert proof["retryable_release_recovery"]["source_attempt_id"] == failed["attempt_id"]
                    uow.cursor.execute("SELECT count(*) FROM authority_attempt WHERE operation_id=%s", [source_id])
                    assert uow.cursor.fetchone()[0] == 1
                    uow.cursor.execute("SELECT count(*) FROM authority_external_effect_dispatch dispatch JOIN authority_external_effect effect USING(external_effect_id) WHERE effect.operation_id=%s", [source_id])
                    assert uow.cursor.fetchone()[0] == 1
                return
            if route_continuation or input_order_continuation:
                from novel_forge.modules.command_kernel.errors import KernelError
                with monkeypatch.context() as historical_route:
                    if route_continuation:
                        from novel_forge.modules.production_execution.cost_routing import CostAwareRouter
                        current_explain = CostAwareRouter.explain
                        def frozen_legacy_explain(router, task, *args, **kwargs):
                            if task.task_type == "chapter_group_plan.generate" and task.history:
                                task = replace(task, declared_requirements={key: value for key, value in task.declared_requirements.items() if key not in {"pure_generation", "governed_repair"}})
                            return current_explain(router, task, *args, **kwargs)
                        historical_route.setattr(CostAwareRouter, "explain", frozen_legacy_explain)
                    with pytest.raises(KernelError, match="NATIVE_PLANNING_REPAIR_SOURCE_INVALID" if input_order_continuation else "PROVIDER_ROUTING_BLOCKED"):
                        continue_creation(composition=composition, content=content, chapter=chapter,
                            formation_run_id=admitted.formation_run_id, formation_worker=formation_worker,
                            book_worker=worker, maximum_ticks=80, deadline=time.monotonic() + 240, creation_policy=policy)
                execution.close()
                formation, execution, chapter, composition = _recover_capacity_formation(harness=harness,
                    chapter_pack=chapter_pack, principal=principal, pack_actor=template_actor, settings=settings,
                    env=env, registry=registry, transport=transport, admitted=admitted, monkeypatch=monkeypatch,
                    routing=True, input_order=input_order_continuation)
            if gateway_null_recovery:
                from novel_forge.modules.command_kernel.errors import KernelError
                with pytest.raises(KernelError,match="MODEL_EFFECT_FINAL_PLANNING"):
                    continue_creation(composition=composition,content=content,chapter=chapter,
                        formation_run_id=admitted.formation_run_id,formation_worker=formation_worker,book_worker=worker,
                        maximum_ticks=80,deadline=time.monotonic()+240,creation_policy=policy)
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT e.external_effect_id,e.operation_id,e.last_error FROM authority_external_effect e WHERE e.project_id=%s AND e.status='FAILED_FINAL'",[harness.project_id])
                    rejected = uow.cursor.fetchone()
                    assert rejected and rejected[2]['production_execution']['execution_result']['outcome']=='FINAL_FAILURE'
                    uow.cursor.execute("SELECT to_jsonb(a) FROM authority_attempt a WHERE operation_id=%s",[rejected[1]])
                    retained_attempt = uow.cursor.fetchone()[0]
                from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext,read_rejected_structured_completion
                from novel_forge.modules.story_planning_runtime.gateway_result_recovery import retained_output
                request = rejected[2]['production_execution']['execution_request']
                context = EffectCommandContext(operation_id=rejected[1],project_id=harness.project_id,
                    actor_id=worker.principal_id,trace_id='trace:revalidation',correlation_id=harness.project_id)
                with pytest.raises(KernelError,match='EFFECT_REJECTED_RESULT_OWNER_INVALID'):
                    read_rejected_structured_completion(DATABASE_URL,replace(context,actor_id='unauthorized:actor'),effect_id=rejected[0])
                with pytest.raises(KernelError,match='EFFECT_REJECTED_RESULT_OWNER_INVALID'):
                    read_rejected_structured_completion(DATABASE_URL,replace(context,project_id='foreign:project'),effect_id=rejected[0])
                from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
                query = AuthorityAssetQuery(DATABASE_URL)
                receipt_ref=rejected[2]['production_execution']['execution_result']['process_receipt_ref'].split(':',1)[1]
                receipt=query.require(project_id=harness.project_id,asset_version_id=receipt_ref)
                raw_path=Path(receipt.content['payload']['result_path'])
                exact_raw = raw_path.read_bytes()
                try:
                    raw_path.write_bytes(exact_raw+b' ')
                    with pytest.raises(KernelError,match='PLANNING_GATEWAY_RESULT_HASH_DRIFT'):
                        retained_output(query,project_id=harness.project_id,provider=rejected[2],request=request)
                finally:
                    raw_path.write_bytes(exact_raw)
                before_local_calls = len(transport.chapter.calls)
            if world_optional_recovery:
                from novel_forge.modules.command_kernel.errors import KernelError
                with pytest.raises(KernelError,match='PLANNING_RESULT_REPAIR_BOUND_EXCEEDED'):
                    continue_creation(composition=composition,content=content,chapter=chapter,
                        formation_run_id=admitted.formation_run_id,formation_worker=formation_worker,book_worker=worker,
                        maximum_ticks=80,deadline=time.monotonic()+240,creation_policy=policy)
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT g.repair_number,o.status FROM authority_story_planning_generation g JOIN authority_operation o USING(operation_id) WHERE g.project_id=%s AND g.generator_operation_name='chapter_plan.generate' ORDER BY g.created_at", [harness.project_id])
                    assert uow.cursor.fetchall() == [(0,'FAILED_FINAL'),(1,'FAILED_FINAL'),(2,'FAILED_FINAL')]
                    uow.cursor.execute("SELECT COALESCE(max(accepted_through_chapter),0) FROM authority_book_production WHERE project_id=%s", [harness.project_id])
                    assert uow.cursor.fetchone() == (0,)
                    uow.cursor.execute("SELECT count(*) FROM authority_asset a JOIN authority_asset_version v USING(asset_id) WHERE a.project_id=%s AND a.asset_type='narrative_governance_action' AND v.content #>> '{contract,world_plan,disposition}'='BLOCKED'", [harness.project_id])
                    assert uow.cursor.fetchone() == (3,)
                execution.close()
                formation,execution,chapter,composition = _recover_capacity_formation(harness=harness,chapter_pack=chapter_pack,
                    principal=principal,pack_actor=template_actor,settings=settings,env=env,registry=registry,
                    transport=transport,admitted=admitted,monkeypatch=monkeypatch,world_optional=True)
            if world_result_repair == "reference-checkpoint":
                from novel_forge.modules.command_kernel.errors import KernelError
                with pytest.raises(KernelError, match="PLANNING_RESULT_REPAIR_SOURCE_INVALID"):
                    continue_creation(composition=composition, content=content, chapter=chapter,
                        formation_run_id=admitted.formation_run_id, formation_worker=formation_worker,
                        book_worker=worker, maximum_ticks=80, deadline=time.monotonic() + 240, creation_policy=policy)
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("""SELECT o.operation_id FROM authority_operation o
                        JOIN authority_story_planning_generation g USING(operation_id)
                        WHERE o.project_id=%s AND o.status='WAITING_EXTERNAL_RESULT'
                        AND g.generator_operation_name='chapter_plan.generate'""", [harness.project_id])
                    checkpoint_operation = uow.cursor.fetchone()[0]
                    uow.cursor.execute("SELECT status,count(*) FROM authority_external_effect WHERE operation_id=%s GROUP BY status", [checkpoint_operation])
                    assert uow.cursor.fetchall() == [("SUCCEEDED", 1)]
                    uow.cursor.execute("SELECT status,checkpoint->>'error_code' FROM authority_attempt WHERE operation_id=%s", [checkpoint_operation])
                    assert uow.cursor.fetchall() == [("CHECKPOINTED", "WORLD_GENERATION_PLAN_REFERENCE_UNKNOWN")]
            if scene_core_recovery or scene_information_recovery or review_knowledge_recovery or length_scope_recovery:
                stopped = continue_creation(composition=composition, content=content, chapter=chapter,
                    formation_run_id=admitted.formation_run_id, formation_worker=formation_worker, book_worker=worker,
                    maximum_ticks=80, deadline=time.monotonic()+240, creation_policy=policy)
                assert stopped['stop_reason'] == ('REVISION_OUTSIDE_DIAGNOSIS_SCOPE' if length_scope_recovery else 'REVIEW_KNOWLEDGE_CHECK_INVALID' if review_knowledge_recovery else 'REALIZATION_EPISTEMIC_SCOPE_VIOLATION' if scene_information_recovery else 'REALIZATION_CAPABILITY_INVALID'), stopped
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT to_jsonb(o),to_jsonb(a) FROM authority_operation o JOIN authority_attempt a USING(operation_id) WHERE o.project_id=%s AND o.definition_name=%s AND o.status IN ('FAILED_FINAL','FAILED_RETRYABLE')", [harness.project_id,'chapter.revision.apply' if length_scope_recovery else 'chapter.review.evaluate' if review_knowledge_recovery else 'chapter.draft.generate'])
                    failed_scene_step = uow.cursor.fetchone()
                    uow.cursor.execute("SELECT to_jsonb(e),to_jsonb(r) FROM authority_external_effect e JOIN authority_budget_reservation r USING(external_effect_id) WHERE e.project_id=%s ORDER BY e.external_effect_id", [harness.project_id])
                    completed_scene_calls = uow.cursor.fetchall()
                monkeypatch.setattr(scene_definitions, 'CHAPTER_DRAFT_DEFINITION_VERSION', saved_draft_version)
                monkeypatch.setattr(scene_definitions, 'CHAPTER_REVIEW_DEFINITION_VERSION', saved_review_version)
                monkeypatch.setattr(scene_definitions, 'CHAPTER_REVISION_DEFINITION_VERSION', saved_revision_version)
                monkeypatch.setattr(Path, 'read_text', normal_scene_read)
                if length_scope_recovery:
                    def old_canon_pack(path, *args, **kwargs):
                        value = normal_scene_read(path, *args, **kwargs)
                        if path.name != 'chapter_generation_pack.json':
                            return value
                        from novel_forge.modules.capability_packs.artifacts import artifact_content_hash
                        from novel_forge.storage.authority_repositories import definition_hash
                        value = json.loads(value)
                        value['identity']['version'] = '2.18.0'
                        value['prompt_binding'].update(template_version='v9', compiler_version='chapter-prompt-compiler:v9',
                            template_hash=artifact_content_hash({'text':normal_scene_read(path.parent/'artifacts/chapter_generation_template_v9.md')}))
                        canon_definition = next(d for d in scene_definitions.chapter_operation_definitions(application_build_id='legacy-canon-fixture',commit_sha='0'*40,model_effects_required=True) if d['name']=='chapter.canon.extract')
                        node = next(n for n in value['workflow_template']['nodes'] if n['operation_name']=='chapter.canon.extract')
                        node.update(operation_definition_ref='chapter.canon.extract@3.9.0',operation_definition_hash=definition_hash(canon_definition))
                        support_definition=next(d for d in scene_definitions.chapter_operation_definitions(application_build_id='legacy-canon-fixture',commit_sha='0'*40,model_effects_required=True) if d['name']=='chapter.canon.propose_changes')
                        support_node=next(n for n in value['workflow_template']['nodes'] if n['operation_name']=='chapter.canon.propose_changes')
                        support_node.update(operation_definition_ref='chapter.canon.propose_changes@3.9.0',operation_definition_hash=definition_hash(support_definition))
                        return json.dumps(value)
                    monkeypatch.setattr(Path,'read_text',old_canon_pack)
                execution.close()
                from tests.integration.creative_validation_production_support import install_planning
                from novel_forge.modules.capability_packs.validation_deployment import register_validation_runtime_definitions, install_chapter_validation_pack
                harness.release_sha = 'e'*40
                hashes = register_validation_runtime_definitions(DATABASE_URL, application_build_id=harness.application_build_id, commit_sha=harness.release_sha)
                harness.pack_id += '.scene-core-successor'
                chapter_pack.pack_id += '.scene-core-successor'
                install_chapter_validation_pack(DATABASE_URL, repository_root=Path(__file__).resolve().parents[2], project_id=harness.project_id,
                    workspace_id=harness.workspace_id, book_id=harness.book_ids[0], application_build_id=harness.application_build_id,
                    commit_sha=harness.release_sha, compiler=template_actor, approver=template_actor, agent_admin=template_actor, pack_id_override=chapter_pack.pack_id)
                install_planning(harness, build_story_planning_pack_profile(Path(__file__).resolve().parents[2], operation_definition_hash=hashes['planning'], pack_id=harness.pack_id), template_actor)
                env.update(NOVEL_FORGE_COMMIT_SHA=harness.release_sha, NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID=harness.pack_id, NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID=chapter_pack.pack_id)
                execution = build_production_execution_composition(settings, env=env, provider_registry=registry, planning_fixture_factory=transport.planning, chapter_fixture_factory=transport.chapter)
                chapter = build_chapter_authority_application(settings, execution=execution, env=env)
                composition = build_book_production_composition(settings, principal=principal, execution=execution, chapter_application=chapter, env=env)
                from novel_forge.modules.command_kernel.step_successor import replace_failed_step
                from novel_forge.modules.command_kernel.service import AdmissionContext
                from novel_forge.modules.command_kernel.errors import KernelError
                recovery_context = AdmissionContext(principal.principal_id, principal.permissions,
                    chapter.registry.available_handler_keys, harness.application_build_id, harness.release_sha)
                for invalid_context, error_code in (
                    (replace(recovery_context, actor_id='foreign:actor'), 'STEP_SUCCESSOR_SOURCE_INVALID'),
                    (replace(recovery_context, permissions=frozenset()), 'PERMISSION_DENIED'),
                ):
                    with pytest.raises(KernelError, match=error_code):
                        replace_failed_step(DATABASE_URL, predecessor_id=failed_scene_step[0]['operation_id'],
                            target_version='3.9.4' if length_scope_recovery else '3.9.3' if review_knowledge_recovery else '3.9.2', context=invalid_context, policy_evidence={},
                            expected_failure_code='REALIZATION_CAPABILITY_INVALID')
            if memo_timeout_recovery:
                try:
                    first=continue_creation(composition=composition,content=content,chapter=chapter,
                        formation_run_id=admitted.formation_run_id,formation_worker=formation_worker,book_worker=worker,
                        maximum_ticks=80,deadline=time.monotonic()+240,creation_policy=policy)
                    assert first['stop_reason']=='WAIT_EXTERNAL_RECONCILIATION', first
                    old_book=composition.authority.require(first['book_run_id'])
                    old_request=composition.authority.require_chapter_request(old_book['active_chapter_request_id'])
                    from novel_forge.modules.command_kernel.budget_runtime import unresolved_cli_outcomes
                    from novel_forge.modules.production_execution.contracts import local_cli_remote_outcome_unknown
                    def memo_unknown_facts():
                        with AuthorityUnitOfWork(DATABASE_URL) as uow:
                            uow.cursor.execute("""SELECT to_jsonb(e),to_jsonb(reservation),to_jsonb(dispatch)
                                FROM authority_external_effect e
                                JOIN authority_operation operation ON operation.operation_id=e.operation_id
                                JOIN authority_budget_reservation reservation USING(external_effect_id)
                                JOIN authority_external_effect_dispatch dispatch USING(external_effect_id)
                                WHERE operation.root_operation_id=%s AND operation.definition_name='chapter.memo.generate'
                                ORDER BY e.external_effect_id,dispatch.generation""",[old_request['chapter_root_operation_id']])
                            receipts=tuple(uow.cursor.fetchall())
                            uow.cursor.execute("""SELECT count(*) FROM authority_external_effect_dispatch dispatch
                                JOIN authority_external_effect effect USING(external_effect_id) WHERE effect.project_id=%s""",[harness.project_id])
                            dispatches=uow.cursor.fetchone()[0]
                            uow.cursor.execute("SELECT count(*) FROM authority_book_chapter_acceptance WHERE project_id=%s",[harness.project_id])
                            accepted=uow.cursor.fetchone()[0]
                            uow.cursor.execute("SELECT count(*) FROM authority_book_chapter_request WHERE predecessor_request_id=%s",[old_request['chapter_request_id']])
                            successors=uow.cursor.fetchone()[0]
                            unknown=unresolved_cli_outcomes(uow.cursor,harness.project_id,root_operation_id=old_request['chapter_root_operation_id'])
                        return receipts,dispatches,accepted,successors,unknown
                    before=memo_unknown_facts()
                    assert len(before[0])==1 and len(before[4])==1 and before[2:4]==(0,0)
                    effect,budget,dispatch=before[0][0]
                    production_receipt=dispatch['evidence']['production_execution']
                    result=production_receipt['execution_result']
                    assert result['outcome']=='TIMED_OUT' and result['started_at'] is not None
                    assert not result.get('usage_receipt_ref') and result.get('process_receipt_ref')
                    assert local_cli_remote_outcome_unknown(transport=production_receipt['execution_handle']['transport'],
                        outcome=result['outcome'],started_at=result['started_at'],usage_receipt_ref=result.get('usage_receipt_ref'))
                    assert before[4][0]['external_effect_id']==effect['external_effect_id'] and before[4][0]['usage']=='UNKNOWN'
                    assert delayed==1
                    if memo_timeout_prefix_recovery:
                        with AuthorityUnitOfWork(DATABASE_URL) as uow:
                            uow.cursor.execute("SELECT definition_snapshot->'retry_policy'->>'max_attempts' FROM authority_operation WHERE operation_id=%s",[effect['operation_id']])
                            assert uow.cursor.fetchone()==('2',)
                    calls_before=(len(transport.calls),len(transport.chapter.calls))
                    resumed=continue_creation(composition=composition,content=content,chapter=chapter,
                        formation_run_id=admitted.formation_run_id,formation_worker=formation_worker,book_worker=worker,
                        maximum_ticks=80,deadline=time.monotonic()+240,creation_policy=policy)
                    assert resumed['stop_reason']=='WAIT_EXTERNAL_RECONCILIATION' and resumed['book_run_id']==old_book['book_run_id']
                    assert memo_unknown_facts()==before
                    assert calls_before==(len(transport.calls),len(transport.chapter.calls)) and delayed==1
                    current_book=composition.authority.require(old_book['book_run_id'])
                    assert current_book['active_chapter_request_id']==old_request['chapter_request_id'] and current_book['accepted_through_chapter']==0
                    return
                finally:
                    execution.close()
            if stage_repair_recovery:
                def stage_wait_facts():
                    with AuthorityUnitOfWork(DATABASE_URL) as uow:
                        uow.cursor.execute("SELECT book_run_id,state,accepted_through_chapter,version FROM authority_book_production WHERE project_id=%s", [harness.project_id])
                        book_fact = uow.cursor.fetchone()
                        uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE project_id=%s", [harness.project_id])
                        effect_count = uow.cursor.fetchone()[0]
                        uow.cursor.execute("SELECT count(*) FROM authority_story_planning_generation WHERE project_id=%s", [harness.project_id])
                        planning_count = uow.cursor.fetchone()[0]
                    return book_fact, effect_count, planning_count, (len(transport.calls), len(transport.chapter.calls))

                before_stage_wait = stage_wait_facts()
                stopped=continue_creation(composition=composition,content=content,chapter=chapter,
                    formation_run_id=admitted.formation_run_id,formation_worker=formation_worker,book_worker=worker,
                    maximum_ticks=80,deadline=time.monotonic()+240,creation_policy=policy)
                if stopped['stop_reason'] == 'WAITING_LEASE_OR_DEPENDENCY':
                    assert stage_wait_facts() == before_stage_wait
                    assert stopped['book_run_id'] == before_stage_wait[0][0]
                    with AuthorityUnitOfWork(DATABASE_URL) as uow:
                        uow.cursor.execute("SELECT runtime_job_id,dedupe_key,input_hash,attempt_count,available_at-clock_timestamp(),last_error->>'code' FROM authority_runtime_job WHERE project_id=%s AND subject_id=%s AND job_kind='BOOK_COORDINATION_TICK' AND status='RETRY_WAIT' ORDER BY available_at LIMIT 1", [harness.project_id, stopped['book_run_id']])
                        waiting_job = uow.cursor.fetchone()
                        assert waiting_job and waiting_job[5] == 'MODEL_EFFECT_FINAL_PLANNING'
                        delay = max(0.0, waiting_job[4].total_seconds())
                        assert delay <= 30
                    time.sleep(min(30, delay + 0.05))
                    with AuthorityUnitOfWork(DATABASE_URL) as uow:
                        uow.cursor.execute("SELECT runtime_job_id,dedupe_key,input_hash,attempt_count,clock_timestamp()>=available_at FROM authority_runtime_job WHERE runtime_job_id=%s", [waiting_job[0]])
                        ready_job = uow.cursor.fetchone()
                        assert ready_job[:4] == waiting_job[:4] and ready_job[4]
                    assert stage_wait_facts() == before_stage_wait
                    stopped=continue_creation(composition=composition,content=content,chapter=chapter,
                        formation_run_id=admitted.formation_run_id,formation_worker=formation_worker,book_worker=worker,
                        maximum_ticks=80,deadline=time.monotonic()+240,creation_policy=policy)
                    assert stopped['book_run_id'] == before_stage_wait[0][0]
                assert stopped['book_run_id']
                waiting=composition.authority.require(stopped['book_run_id'])
                assert waiting['state']=='PLAN_APPROVAL_PENDING'
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT operation_id,candidate_asset_version_id FROM authority_story_planning_generation WHERE project_id=%s AND generator_operation_name='chapter_plan.generate' AND status='REJECTED'",[harness.project_id])
                    rejected_stage = uow.cursor.fetchone()
                    assert rejected_stage
                execution.close()
                formation,execution,chapter,composition=_recover_capacity_formation(harness=harness,chapter_pack=chapter_pack,
                    principal=principal,pack_actor=template_actor,settings=settings,env=env,registry=registry,
                    transport=transport,admitted=admitted,monkeypatch=monkeypatch,stage_repairs=True)
            if scene_information_recovery or length_scope_recovery:
                from datetime import timedelta
                from novel_forge.modules.command_kernel import execution_window
                original_window = execution_window.continue_candidate_execution_window
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute('SELECT business_deadline_at FROM authority_operation WHERE operation_id=%s', [failed_scene_step[0]['root_operation_id']])
                    frozen_scene_deadline = uow.cursor.fetchone()[0]
                def expired_window(url, **kwargs):
                    source_deadline = frozen_scene_deadline
                    if kwargs['target_version'] in {'3.9.7','3.9.8'}:
                        with AuthorityUnitOfWork(url) as uow:
                            uow.cursor.execute('SELECT business_deadline_at FROM authority_operation WHERE operation_id=%s',[kwargs['root_id']])
                            source_deadline = uow.cursor.fetchone()[0]
                    first = original_window(url, **kwargs, clock=lambda: source_deadline+timedelta(seconds=1))
                    assert first['continued'] and not first['replayed']
                    replay = original_window(url, **kwargs, clock=lambda: first['deadline']+timedelta(seconds=1))
                    assert replay['replayed'] and replay['deadline'] == first['deadline'].isoformat()
                    if kwargs.get('start_repair_phase'):
                        with AuthorityUnitOfWork(url) as uow:
                            uow.cursor.execute('SELECT business_deadline_at FROM authority_operation WHERE operation_id=%s',[kwargs['predecessor_id']])
                            assert uow.cursor.fetchone()[0] > frozen_scene_deadline+timedelta(seconds=1)
                    return first
                monkeypatch.setattr(execution_window,'continue_candidate_execution_window',expired_window)
                if length_scope_recovery:
                    from novel_forge.modules.chapter_authority import scheduler as scheduler_module
                    from novel_forge.modules.chapter_authority.execution_gateway import PostgresChapterExecutionContractBinder
                    from novel_forge.modules.production_execution.routing_runtime import ProductionProviderRouter
                    from novel_forge.modules.command_kernel.errors import KernelError
                    from novel_forge.modules.chapter_authority import candidate_repair
                    original_canon_recovery = candidate_repair.recover_canon_capacity_frontier
                    monkeypatch.setattr(candidate_repair,'recover_canon_capacity_frontier',lambda *a,**k: False)
                    normal_canon_contract = PostgresChapterExecutionContractBinder._provider_output_contract
                    normal_route = ProductionProviderRouter.select
                    canon_capacity_rejected = False
                    def inline_first_canon(**kwargs):
                        if kwargs['stage']=='canon_extraction' and not canon_capacity_rejected:
                            kwargs['prompt_contract_version']='v9'
                        return normal_canon_contract(**kwargs)
                    def controlled_capacity_route(router, base, **kwargs):
                        nonlocal canon_capacity_rejected
                        candidates = router.candidates
                        if kwargs['task_type']=='canon_extraction' and not canon_capacity_rejected:
                            canon_capacity_rejected = True
                            router.candidates = tuple(replace(c,context_limit=kwargs['input_tokens']+kwargs['output_tokens']-1) for c in candidates)
                        try:
                            return normal_route(router,base,**kwargs)
                        finally:
                            router.candidates=candidates
                    monkeypatch.setattr(PostgresChapterExecutionContractBinder,'_provider_output_contract',staticmethod(inline_first_canon))
                    monkeypatch.setattr(ProductionProviderRouter,'select',controlled_capacity_route)
                    normal_probe = scheduler_module.probe_operation_execution
                    no_send_timeout = False
                    def controlled_no_send_timeout(url, *, operation_id, project_id):
                        nonlocal no_send_timeout
                        with AuthorityUnitOfWork(url) as uow:
                            uow.cursor.execute("SELECT o.definition_version,a.attempt_number FROM authority_operation o JOIN authority_attempt a USING(operation_id) WHERE o.operation_id=%s AND a.status='RUNNING'",[operation_id])
                            current = uow.cursor.fetchone()
                        if current == ('3.9.4',2) and not no_send_timeout:
                            no_send_timeout = True
                            raise KernelError('OPERATION_BUSINESS_TIMEOUT','Controlled pre-dispatch child deadline failure; no Provider call')
                        return normal_probe(url,operation_id=operation_id,project_id=project_id)
                    monkeypatch.setattr(scheduler_module,'probe_operation_execution',controlled_no_send_timeout)
            def wait_facts():
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT book_run_id,state,accepted_through_chapter,version FROM authority_book_production WHERE project_id=%s", [harness.project_id])
                    book_fact = uow.cursor.fetchone()
                    uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE project_id=%s", [harness.project_id])
                    effect_count = uow.cursor.fetchone()[0]
                    uow.cursor.execute("SELECT count(*) FROM authority_story_planning_generation WHERE project_id=%s", [harness.project_id])
                    planning_count = uow.cursor.fetchone()[0]
                return book_fact, effect_count, planning_count, (len(transport.calls),len(transport.chapter.calls))
            before_native_wait = wait_facts()
            creation_result = continue_creation(composition=composition, content=content, chapter=chapter,
                formation_run_id=admitted.formation_run_id, formation_worker=formation_worker,
                book_worker=worker, maximum_ticks=80, deadline=time.monotonic() + 240, creation_policy=policy)
            previous_window = before_native_wait
            while valid_result_admission and creation_result['stop_reason'] == 'YIELDED_CHECKPOINT':
                current_window = wait_facts()
                assert current_window != previous_window, 'Checkpoint yielded without native progress'
                previous_window = current_window
                creation_result = continue_creation(composition=composition, content=content, chapter=chapter,
                    formation_run_id=admitted.formation_run_id, formation_worker=formation_worker,
                    book_worker=worker, maximum_ticks=80, deadline=time.monotonic()+240, creation_policy=policy)
            if creation_result['stop_reason'] == 'WAITING_LEASE_OR_DEPENDENCY' and (world_optional_recovery or world_result_repair or input_order_continuation or route_continuation or gateway_null_recovery):
                assert wait_facts() == before_native_wait
                original_book_run = creation_result['book_run_id']
                assert original_book_run == before_native_wait[0][0]
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT runtime_job_id,dedupe_key,input_hash,attempt_count,available_at-clock_timestamp(),last_error->>'code' FROM authority_runtime_job WHERE project_id=%s AND subject_id=%s AND job_kind='BOOK_COORDINATION_TICK' AND status='RETRY_WAIT' ORDER BY available_at LIMIT 1", [harness.project_id,original_book_run])
                    waiting_job = uow.cursor.fetchone()
                    assert waiting_job and waiting_job[5] in ({'PLANNING_RESULT_REPAIR_BOUND_EXCEEDED','NATIVE_PLANNING_REPAIR_SOURCE_INVALID','PROVIDER_ROUTING_BLOCKED','MODEL_EFFECT_FINAL_PLANNING'} | ({'PLANNING_RESULT_REPAIR_SOURCE_INVALID'} if world_result_repair else set()))
                    delay = max(0.0,waiting_job[4].total_seconds())
                    assert delay <= 30
                time.sleep(min(30,delay+0.05))
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT runtime_job_id,dedupe_key,input_hash,attempt_count,clock_timestamp()>=available_at FROM authority_runtime_job WHERE runtime_job_id=%s", [waiting_job[0]])
                    ready_job = uow.cursor.fetchone()
                    assert ready_job[:4] == waiting_job[:4] and ready_job[4]
                assert wait_facts() == before_native_wait
                creation_result = continue_creation(composition=composition, content=content, chapter=chapter,
                    formation_run_id=admitted.formation_run_id, formation_worker=formation_worker,
                    book_worker=worker, maximum_ticks=80, deadline=time.monotonic()+240, creation_policy=policy)
                assert creation_result['book_run_id'] == original_book_run
            if length_scope_recovery:
                assert creation_result['stop_reason']=='PROVIDER_ROUTING_BLOCKED', creation_result
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT to_jsonb(o),to_jsonb(a) FROM authority_operation o JOIN authority_attempt a USING(operation_id) WHERE o.root_operation_id=%s AND o.definition_name='chapter.canon.extract'",[failed_scene_step[0]['root_operation_id']])
                    retained_canon = uow.cursor.fetchone()
                    uow.cursor.execute('SELECT to_jsonb(s) FROM authority_attempt_capability_pack_snapshot s WHERE attempt_id=%s',[retained_canon[1]['attempt_id']])
                    retained_canon_pack = uow.cursor.fetchone()
                    uow.cursor.execute('SELECT count(*) FROM authority_external_effect WHERE operation_id=%s',[retained_canon[0]['operation_id']])
                    assert uow.cursor.fetchone()==(0,)
                monkeypatch.setattr(scene_definitions,'CHAPTER_CANON_DEFINITION_VERSION',saved_canon_version)
                def current_canon_legacy_support_pack(path,*args,**kwargs):
                    value=normal_scene_read(path,*args,**kwargs)
                    if path.name!='chapter_generation_pack.json':
                        return value
                    from novel_forge.storage.authority_repositories import definition_hash
                    value=json.loads(value)
                    value['identity']['version']='2.21.0'
                    definition=next(d for d in scene_definitions.chapter_operation_definitions(application_build_id='retained-support',commit_sha='0'*40,model_effects_required=True) if d['name']=='chapter.canon.propose_changes')
                    node=next(n for n in value['workflow_template']['nodes'] if n['operation_name']=='chapter.canon.propose_changes')
                    node.update(operation_definition_ref='chapter.canon.propose_changes@3.9.0',operation_definition_hash=definition_hash(definition))
                    return json.dumps(value)
                monkeypatch.setattr(Path,'read_text',current_canon_legacy_support_pack)
                monkeypatch.setattr(candidate_repair,'recover_canon_capacity_frontier',original_canon_recovery)
                execution.close()
                harness.release_sha = 'd'*40
                hashes = register_validation_runtime_definitions(DATABASE_URL,application_build_id=harness.application_build_id,commit_sha=harness.release_sha)
                harness.pack_id += '.canon-successor'
                chapter_pack.pack_id += '.canon-successor'
                install_chapter_validation_pack(DATABASE_URL,repository_root=Path(__file__).resolve().parents[2],project_id=harness.project_id,
                    workspace_id=harness.workspace_id,book_id=harness.book_ids[0],application_build_id=harness.application_build_id,
                    commit_sha=harness.release_sha,compiler=template_actor,approver=template_actor,agent_admin=template_actor,pack_id_override=chapter_pack.pack_id)
                install_planning(harness,build_story_planning_pack_profile(Path(__file__).resolve().parents[2],operation_definition_hash=hashes['planning'],pack_id=harness.pack_id),template_actor)
                env.update(NOVEL_FORGE_COMMIT_SHA=harness.release_sha,NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID=harness.pack_id,NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID=chapter_pack.pack_id)
                execution=build_production_execution_composition(settings,env=env,provider_registry=registry,planning_fixture_factory=transport.planning,chapter_fixture_factory=transport.chapter)
                chapter=build_chapter_authority_application(settings,execution=execution,env=env)
                composition=build_book_production_composition(settings,principal=principal,execution=execution,chapter_application=chapter,env=env)
                creation_result=continue_creation(composition=composition,content=content,chapter=chapter,
                    formation_run_id=admitted.formation_run_id,formation_worker=formation_worker,book_worker=worker,
                    maximum_ticks=80,deadline=time.monotonic()+240,creation_policy=policy)
                assert creation_result['stop_reason']=='CANON_GROUNDING_REEXTRACTION_REQUIRED',creation_result
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT o.operation_id,to_jsonb(a) FROM authority_operation o JOIN authority_attempt a USING(operation_id) WHERE o.root_operation_id=%s AND o.definition_name='chapter.canon.propose_changes' AND o.definition_version='3.9.0'",[failed_scene_step[0]['root_operation_id']])
                    old_support=uow.cursor.fetchone()
                monkeypatch.setattr(scene_definitions,'CHAPTER_SUPPORT_DEFINITION_VERSION',saved_support_version)
                monkeypatch.setattr(Path,'read_text',normal_scene_read)
                execution.close()
                harness.release_sha='c'*40
                hashes=register_validation_runtime_definitions(DATABASE_URL,application_build_id=harness.application_build_id,commit_sha=harness.release_sha)
                harness.pack_id += '.support-successor'
                chapter_pack.pack_id += '.support-successor'
                install_chapter_validation_pack(DATABASE_URL,repository_root=Path(__file__).resolve().parents[2],project_id=harness.project_id,
                    workspace_id=harness.workspace_id,book_id=harness.book_ids[0],application_build_id=harness.application_build_id,
                    commit_sha=harness.release_sha,compiler=template_actor,approver=template_actor,agent_admin=template_actor,pack_id_override=chapter_pack.pack_id)
                install_planning(harness,build_story_planning_pack_profile(Path(__file__).resolve().parents[2],operation_definition_hash=hashes['planning'],pack_id=harness.pack_id),template_actor)
                env.update(NOVEL_FORGE_COMMIT_SHA=harness.release_sha,NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID=harness.pack_id,NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID=chapter_pack.pack_id)
                execution=build_production_execution_composition(settings,env=env,provider_registry=registry,planning_fixture_factory=transport.planning,chapter_fixture_factory=transport.chapter)
                chapter=build_chapter_authority_application(settings,execution=execution,env=env)
                composition=build_book_production_composition(settings,principal=principal,execution=execution,chapter_application=chapter,env=env)
                creation_result=continue_creation(composition=composition,content=content,chapter=chapter,
                    formation_run_id=admitted.formation_run_id,formation_worker=formation_worker,book_worker=worker,
                    maximum_ticks=80,deadline=time.monotonic()+240,creation_policy=policy)
                assert support_calls==2
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute('SELECT to_jsonb(a) FROM authority_attempt a WHERE attempt_id=%s',[old_support[1]['attempt_id']])
                    assert uow.cursor.fetchone()==(old_support[1],)
                    uow.cursor.execute('SELECT status FROM authority_operation WHERE operation_id=%s',[old_support[0]])
                    assert uow.cursor.fetchone()==('CANCELLED',)
                    uow.cursor.execute("SELECT o.status,o.definition_version FROM authority_saga_step_successor s JOIN authority_operation o ON o.operation_id=s.successor_operation_id WHERE s.predecessor_operation_id=%s",[old_support[0]])
                    assert uow.cursor.fetchone()==('SUCCEEDED','3.9.8')
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute('SELECT to_jsonb(a) FROM authority_attempt a WHERE attempt_id=%s',[retained_canon[1]['attempt_id']])
                    assert uow.cursor.fetchone()==(retained_canon[1],)
                    uow.cursor.execute('SELECT status FROM authority_operation WHERE operation_id=%s',[retained_canon[0]['operation_id']])
                    assert uow.cursor.fetchone()==('CANCELLED',)
                    uow.cursor.execute('SELECT to_jsonb(s) FROM authority_attempt_capability_pack_snapshot s WHERE attempt_id=%s',[retained_canon[1]['attempt_id']])
                    assert uow.cursor.fetchone()==retained_canon_pack
                    uow.cursor.execute('SELECT count(*) FROM authority_external_effect WHERE operation_id=%s',[retained_canon[0]['operation_id']])
                    assert uow.cursor.fetchone()==(0,)
                    uow.cursor.execute("SELECT o.status,o.definition_version FROM authority_saga_step_successor s JOIN authority_operation o ON o.operation_id=s.successor_operation_id WHERE s.predecessor_operation_id=%s",[retained_canon[0]['operation_id']])
                    assert uow.cursor.fetchone()==('SUCCEEDED','3.9.7')
            if scene_information_recovery:
                assert creation_result['stop_reason'] == 'REALIZATION_EPISTEMIC_SCOPE_VIOLATION', creation_result
                creation_result = continue_creation(composition=composition,content=content,chapter=chapter,
                    formation_run_id=admitted.formation_run_id,formation_worker=formation_worker,book_worker=worker,
                    maximum_ticks=80,deadline=time.monotonic()+240,creation_policy=policy)
                assert information_call_count == 3
            assert creation_result["stop_reason"] == "COMPLETED", creation_result
            if scene_core_recovery or scene_information_recovery or review_knowledge_recovery or length_scope_recovery:
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT to_jsonb(o),to_jsonb(a) FROM authority_operation o JOIN authority_attempt a USING(operation_id) WHERE o.operation_id=%s", [failed_scene_step[0]['operation_id']])
                    retained = uow.cursor.fetchone()
                    assert retained[1] == failed_scene_step[1]
                    assert retained[0]['definition_snapshot'] == failed_scene_step[0]['definition_snapshot']
                    assert retained[0]['input_asset_snapshot'] == failed_scene_step[0]['input_asset_snapshot']
                    if scene_information_recovery or length_scope_recovery:
                        assert retained[0]['status'] == 'CANCELLED'
                    else:
                        assert retained == failed_scene_step
                    for effect, reservation in completed_scene_calls:
                        uow.cursor.execute("SELECT to_jsonb(e),to_jsonb(r) FROM authority_external_effect e JOIN authority_budget_reservation r USING(external_effect_id) WHERE e.external_effect_id=%s", [effect['external_effect_id']])
                        assert uow.cursor.fetchone() == (effect, reservation)
                    uow.cursor.execute("SELECT o.status,o.definition_version FROM authority_saga_step_successor s JOIN authority_operation o ON o.operation_id=s.successor_operation_id WHERE s.predecessor_operation_id=%s", [failed_scene_step[0]['operation_id']])
                    assert uow.cursor.fetchone() == ('SUCCEEDED','3.9.4' if length_scope_recovery else '3.9.3' if review_knowledge_recovery else '3.9.2')
                    if review_knowledge_recovery:
                        assert review_scope_calls == 2
                    if length_scope_recovery:
                        assert length_revision_calls == 3
                        assert no_send_timeout
                        assert canon_capacity_rejected
                        uow.cursor.execute("SELECT a.attempt_number,a.status,a.result->>'error_code' FROM authority_attempt a JOIN authority_saga_step s USING(operation_id) JOIN authority_operation o USING(operation_id) WHERE o.root_operation_id=%s AND o.definition_version='3.9.4' ORDER BY a.attempt_number",[failed_scene_step[0]['root_operation_id']])
                        assert uow.cursor.fetchall() == [(1,'FAILED_RETRYABLE','CHAPTER_LENGTH_REPAIR_INCOMPLETE'),(2,'FAILED_RETRYABLE','OPERATION_BUSINESS_TIMEOUT'),(3,'SUCCEEDED',None)]
                        uow.cursor.execute("SELECT a.attempt_number,a.status,a.result->>'error_code' FROM authority_attempt a JOIN authority_saga_step s USING(operation_id) JOIN authority_operation o USING(operation_id) WHERE o.root_operation_id=%s AND o.definition_name='chapter.canon.extract' ORDER BY a.attempt_number",[failed_scene_step[0]['root_operation_id']])
                        assert uow.cursor.fetchall() == [(1,'SUCCEEDED',None)]
            if stage_repair_recovery:
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT g.repair_number,g.status,o.status FROM authority_story_planning_generation g JOIN authority_operation o USING(operation_id) WHERE g.project_id=%s AND g.generator_operation_name='chapter_plan.generate' ORDER BY g.created_at",[harness.project_id])
                    assert uow.cursor.fetchall()==[(0,'ADMITTED','FAILED_FINAL'),(1,'ADMITTED','FAILED_FINAL'),(2,'REJECTED','FAILED_FINAL'),(3,'ACTIVE','SUCCEEDED')]
                    uow.cursor.execute("SELECT request_payload #> '{_production_execution,capability_runtime,routing_decision}' FROM authority_external_effect WHERE project_id=%s AND request_payload->>'stage'='chapter_plan.generate' ORDER BY created_at DESC LIMIT 1",[harness.project_id])
                    stage_decision=uow.cursor.fetchone()[0]
                    assert stage_decision['task']['declared_requirements']['governed_repair']['stage_repair_number']==1
                    assert stage_decision['task']['declared_requirements']['governed_repair']['repair_number']==3
            if gateway_null_recovery:
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT status FROM authority_external_effect WHERE external_effect_id=%s",[rejected[0]])
                    assert uow.cursor.fetchone()==('FAILED_FINAL',)
                    uow.cursor.execute("SELECT to_jsonb(a) FROM authority_attempt a WHERE operation_id=%s",[rejected[1]])
                    assert uow.cursor.fetchone()[0]==retained_attempt
                    uow.cursor.execute("SELECT status FROM authority_budget_reservation WHERE external_effect_id=%s",[rejected[0]])
                    assert uow.cursor.fetchone()==('SETTLED',)
                    uow.cursor.execute("SELECT o.status,g.status,g.repair_number FROM authority_operation o JOIN authority_story_planning_generation g USING(operation_id) WHERE o.operation_id=%s",[rejected[1]])
                    assert uow.cursor.fetchone()==('FAILED_FINAL','REJECTED' if stage_repair_recovery else 'ACTIVE',2 if stage_repair_recovery else 0)
                    uow.cursor.execute("SELECT r.evidence,o.status FROM authority_planning_result_admission r JOIN authority_operation o ON o.operation_id=r.recovery_operation_id WHERE r.source_operation_id=%s",[rejected[1]])
                    local = uow.cursor.fetchone()
                    assert local[1]=='SUCCEEDED' and local[0]['provider_invoked'] is False
                    assert local[0]['current_result_validation']=='VALID' and local[0]['literary_qualification']=='NOT_RUN'
                    uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE operation_id=%s AND request_payload->>'stage'='chapter_plan.generate'",[rejected[1]])
                    assert uow.cursor.fetchone()==(1,)
                assert len([c for c in transport.chapter.calls if c['stage']=='chapter_plan.generate'])==(2 if stage_repair_recovery else 1)
                assert len(transport.chapter.calls)>before_local_calls
            if world_disabled or world_optional_recovery:
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT e.status,r.status FROM authority_external_effect e JOIN authority_budget_reservation r USING(external_effect_id) WHERE e.project_id=%s AND e.request_payload->>'stage' IN ('world_candidates.generate','world_candidates.evaluate')", [harness.project_id])
                    assert uow.cursor.fetchall() == ([('SUCCEEDED','SETTLED')]*6 if world_optional_recovery else [])
                actions = AuthorityAssetQuery(DATABASE_URL).list_versions(project_id=harness.project_id,asset_type='narrative_governance_action')
                deferred = [a for a in actions if a.content.get('contract',{}).get('optional_preparation')]
                assert deferred and all(a.content['contract']['world_plan']['disposition']=='DEFER' for a in deferred)
                assert all(a.content['contract']['optional_preparation']['status']=='NOT_RUN' for a in deferred)
                if world_optional_recovery:
                    with AuthorityUnitOfWork(DATABASE_URL) as uow:
                        uow.cursor.execute("SELECT g.repair_number,o.status FROM authority_story_planning_generation g JOIN authority_operation o USING(operation_id) WHERE g.generator_operation_name='chapter_plan.generate' AND o.project_id=%s ORDER BY o.created_at",[harness.project_id])
                        assert uow.cursor.fetchall() == [(0,'FAILED_FINAL'),(1,'FAILED_FINAL'),(2,'FAILED_FINAL'),(0,'SUCCEEDED')]
            if world_result_repair and not stage_repair_recovery:
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT g.repair_number,o.status,g.candidate_asset_version_id,g.operation_id FROM authority_story_planning_generation g JOIN authority_operation o USING(operation_id) WHERE o.project_id=%s AND g.generator_operation_name='chapter_plan.generate' ORDER BY o.created_at", [harness.project_id])
                    world_generations = uow.cursor.fetchall()
                    assert [row[:2] for row in world_generations] == [(0, "FAILED_FINAL"), (1, "SUCCEEDED")]
                    assert world_generations[0][2] is None and world_generations[1][2]
                    uow.cursor.execute("SELECT status,count(*) FROM authority_external_effect WHERE operation_id=%s GROUP BY status", [world_generations[0][3]])
                    assert uow.cursor.fetchall() == [("SUCCEEDED", 1)]
                    uow.cursor.execute("SELECT command_payload->'payload' FROM authority_operation WHERE operation_id=%s", [world_generations[0][3]])
                    world_original = uow.cursor.fetchone()[0]
                from novel_forge.modules.story_planning_runtime.application import _command_from_payload
                world_call_count = len(transport.calls), len(transport.chapter.calls)
                original_world_command = _command_from_payload(world_original)
                from novel_forge.modules.command_kernel.errors import KernelError
                with pytest.raises(KernelError, match="PLANNING_GENERATION_COMMAND_IDENTITY_DRIFT"):
                    formation.generation.planning.generate(replace(original_world_command, execution_contract_version="1.19.0"), principal=worker)
                world_replay = formation.generation.planning.generate(original_world_command, principal=worker)
                assert world_replay.candidate_asset_version_id == world_generations[1][2]
                assert world_call_count == (len(transport.calls), len(transport.chapter.calls))
            if semantic_repair:
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT g.repair_number,o.status,g.candidate_asset_version_id FROM authority_story_planning_generation g JOIN authority_operation o USING(operation_id) WHERE o.project_id=%s AND g.generator_operation_name='chapter_group_plan.generate' ORDER BY o.created_at", [harness.project_id])
                    groups = uow.cursor.fetchall()
                    expected = [0, 1, 2, 2, 0, 0] if input_order_continuation else [0, 1, 1, 0, 0] if route_continuation else [0, 1, 0, 0]
                    assert [row[0] for row in groups] == expected
                    assert all(row[1] == "SUCCEEDED" and row[2] for row in groups if row[1] not in {"CANCELLED","FAILED_FINAL"})
                    if route_continuation:
                        assert groups[1][1:] == ("CANCELLED", None)
                    if input_order_continuation:
                        assert groups[2][1:] == ("FAILED_FINAL", None)
                    uow.cursor.execute("SELECT e.request_payload #> '{_production_execution,capability_runtime,routing_decision}' FROM authority_external_effect e JOIN authority_story_planning_generation g USING(operation_id) WHERE e.project_id=%s AND g.generator_operation_name='chapter_group_plan.generate' AND g.repair_number=%s", [harness.project_id,2 if input_order_continuation else 1])
                    decision = uow.cursor.fetchone()[0]
                    proof = decision["task"]["declared_requirements"]["governed_repair"]
                    assert proof["contract_version"] == "planning-route-repair.v1"
                    assert proof["repair_number"] == (2 if input_order_continuation else 1)
                    assert proof["authorized_history_operation_ids"]
                    assert "native_planning_repair" not in decision["task"]["declared_requirements"]
                    assert "native_repair_admission" not in decision["selected"]
                    assert any(item.get("failure_class") == "SCHEMA_REJECTION" for item in decision["task"]["history"])
            book_run = SimpleNamespace(book_run_id=creation_result["book_run_id"])
            calls = len(transport.calls), len(transport.chapter.calls)
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT count(*),sum(actual_tokens) FROM authority_budget_reservation WHERE project_id=%s", [harness.project_id])
                ledger = uow.cursor.fetchone()
                uow.cursor.execute("SELECT count(*) FROM authority_capability_pack_approval approval JOIN authority_operation op ON op.operation_id=approval.decided_by_operation_id WHERE op.project_id=%s", [harness.project_id])
                assert uow.cursor.fetchone()[0] == 0
            execution.close()
            if route_continuation:
                from novel_forge.modules.capability_packs.validation_deployment import register_validation_runtime_definitions, install_chapter_validation_pack
                from tests.integration.creative_validation_production_support import install_planning
                sha = "c" * 40
                hashes = register_validation_runtime_definitions(DATABASE_URL, application_build_id=harness.application_build_id, commit_sha=sha)
                harness.release_sha = sha
                harness.pack_id += ".replay"
                chapter_pack.pack_id += ".replay"
                install_chapter_validation_pack(DATABASE_URL, repository_root=Path(__file__).resolve().parents[2],
                    project_id=harness.project_id, workspace_id=harness.workspace_id, book_id=harness.book_ids[0],
                    application_build_id=harness.application_build_id, commit_sha=sha, compiler=template_actor,
                    approver=template_actor, agent_admin=template_actor, pack_id_override=chapter_pack.pack_id)
                profile = build_story_planning_pack_profile(Path(__file__).resolve().parents[2],
                    operation_definition_hash=hashes["planning"], pack_id=harness.pack_id)
                install_planning(harness, profile, template_actor)
                env.update(NOVEL_FORGE_COMMIT_SHA=sha, NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID=harness.pack_id,
                    NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID=chapter_pack.pack_id)
            execution = build_production_execution_composition(settings, env=env, provider_registry=registry,
                planning_fixture_factory=transport.planning, chapter_fixture_factory=transport.chapter)
            chapter = build_chapter_authority_application(settings, execution=execution, env=env)
            rebuilt = build_book_production_composition(settings, principal=principal, execution=execution,
                chapter_application=chapter, env=env)
            if route_continuation:
                from novel_forge.modules.story_planning_runtime.application import _command_from_payload
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute("SELECT o.command_payload->'payload' FROM authority_story_planning_generation g JOIN authority_operation o USING(operation_id) WHERE o.project_id=%s AND g.generator_operation_name='chapter_group_plan.generate' AND g.repair_number=0 ORDER BY o.created_at LIMIT 1", [harness.project_id])
                    original = _command_from_payload(uow.cursor.fetchone()[0])
                replayed = rebuilt.formation.generation.planning.generate(original, principal=principal)
                assert replayed.candidate_asset_version_id
                assert (len(transport.calls), len(transport.chapter.calls)) == calls
            resumed = continue_creation(composition=rebuilt, content=content, chapter=chapter,
                formation_run_id=admitted.formation_run_id, formation_worker=formation_worker,
                book_worker=worker, maximum_ticks=5, deadline=time.monotonic() + 30, creation_policy=policy)
            assert resumed["stop_reason"] == "COMPLETED" and resumed["book_run_id"] == book_run.book_run_id
            assert (len(transport.calls), len(transport.chapter.calls)) == calls
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute("SELECT count(*),sum(actual_tokens) FROM authority_budget_reservation WHERE project_id=%s", [harness.project_id])
                assert uow.cursor.fetchone() == ledger
        else:
            prepared = prepare_creation_inputs(
                composition=composition,
                content=content,
                formation_run_id=admitted.formation_run_id,
                policy=policy,
            )
            versions = prepared["versions"]
            opening_request = OpenBookProductionRequest(
                project_id=harness.project_id,
                workspace_id=harness.workspace_id,
                book_id=harness.book_ids[0],
                actor_id=principal.principal_id,
                expected_book_version=prepared["book_version"],
                production_profile=versions["production_profile"],
                planning_input_versions={
                    role: versions[role] for role in _OPENING_INPUT_ROLES
                },
                arc_logical_keys=("arc:central", "arc:relationship"),
                idempotency_key=f"{harness.project_id}:synthesis:opening",
                trace_id="trace:synthesis:opening",
                correlation_id=harness.project_id,
                initial_story_state_version=versions["story_state"],
                initial_canon_snapshot_version=versions["canon_snapshot"],
            )
            opening = composition.open_book(opening_request)
            assert opening.opening_run_id
            claim = composition.opening.claim_next_execution(
                worker_id="synthesis-opening",
                lease_seconds=60,
                project_id=harness.project_id,
            )
            assert claim is not None
            opened = execute_book_opening_claim(
                RuntimeJobAuthority(DATABASE_URL),
                composition.opening,
                principal,
                claim,
                lease_seconds=60,
            )
            snapshot = composition.input_resolver.require(opened["input_snapshot_id"])
            if creative_validation:
                from novel_forge.modules.book_authority.creation_runtime import drive_book as drive, resolved_book_command as start_command
            else:
                from scripts.run_world_production_smoke import drive, start_command
            from novel_forge.modules.authority_security import PrincipalType
            import time

            book_run = composition.authority.start(
                start_command(
                    snapshot,
                    actor=principal.principal_id,
                    run_key=f"{harness.project_id}:synthesis:production",
                    chapters=target_chapters,
                ),
                principal=principal,
            )
            worker = replace(
                principal,
                principal_type=PrincipalType.WORKER,
                permissions=principal.permissions - {"book.authority.approve_replan"},
            )
            ticks = []
            stop = drive(
                composition=composition,
                chapter=chapter,
                book_run_id=book_run.book_run_id,
                worker=worker,
                events=ticks.append,
                maximum_ticks=80,
                deadline=time.monotonic() + 240,
            )
            assert stop == ("COMPLETED" if creative_validation else "ACCEPTED_TARGET_REACHED"), (stop, ticks[-3:])
        from tests.integration.creative_grounding_support import (
            verify_creative_workspace,
        )

        workspaces = verify_creative_workspace(
            composition=composition,
            chapter_application=chapter,
            book_run_id=book_run.book_run_id,
            transport=transport.chapter,
            minimum_chapters=min(2, target_chapters),
        )
        if advice_only:
            from novel_forge.modules.review.diagnostics import prose_repair_diagnoses

            for workspace in workspaces["workspaces"]:
                candidates = {item["asset_type"]: item for item in workspace["artifacts"]["candidates"]}
                draft = candidates["draft_chapter"]["content"]
                revision = candidates["draft_version"]["content"]
                assert revision["text"] == draft["text"]
                assert revision["scene_artifacts"] == draft["scene_artifacts"]
                assert candidates["best_draft_candidate"]["content"]["selected_source_asset_version_id"] == candidates["draft_chapter"]["asset_version_id"]
            reviews = [call for call in transport.chapter.calls if call["stage"] == "review"]
            assert len(reviews) == 3
            assert all(call["output"]["issues"][0]["judgment_kind"] == "AESTHETIC_SUGGESTION" for call in reviews)
            revisions = [call for call in transport.chapter.calls if call["stage"] == "revision"]
            assert len(revisions) == 3
            assert any(call["input"]["review"].get("cross_chapter_window") for call in revisions)
            assert all(not prose_repair_diagnoses(call["input"]["review"], work_requirements=True) for call in revisions)
            targeted = [call for call in revisions if call["input"]["review"].get("cross_chapter_window") or call["input"]["review"].get("craft_targets")]
            assert targeted
            assert all(call["output"] == {"edits": [], "resolved_issue_codes": []} for call in targeted)
            from novel_forge.modules.book_followup_authority.prose_coordinator import load_accepted_sources
            from novel_forge.modules.book_followup_authority.prose_review import freeze_manifest

            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                sources = load_accepted_sources(uow, book_run.book_run_id, harness.project_id)
            baselines = {
                workspace["acceptance"]["accepted_through_chapter"]: next(
                    item["content"]["creative_baseline"] for item in workspace["artifacts"]["candidates"]
                    if item["asset_type"] == "best_draft_candidate"
                ) for workspace in workspaces["workspaces"]
            }
            assert {source["chapter_number"]: source["creative_baseline"] for source in sources} == baselines
            manifest = freeze_manifest(
                project_id=harness.project_id, workspace_id=harness.workspace_id,
                book_run_id=book_run.book_run_id, sources=sources,
                policy={"policy_version": "work-fixture", "window_codepoints": 2048,
                        "overlap_codepoints": 64, "context_token_budget": 16000, "maximum_windows": 20},
            )
            assert all(source["work_intent_status"] == "FROZEN_CANDIDATE_BASELINE" for source in manifest["sources"])
        from novel_forge.modules.chapter_outcome.acceptance_contract import resolve_accepted_manuscript

        for workspace in workspaces["workspaces"]:
            assert workspace["accepted_manuscript"]["status"] == "EXACT_ACCEPTANCE_BOUND", workspace["accepted_manuscript"]
            accepted_text = resolve_accepted_manuscript(workspace)
            assert accepted_text["candidate"]["content"]["text"]
            assert accepted_text["outcome"]["asset_version_id"] == workspace["acceptance"]["outcome_asset_version_id"]
            assert workspace["creation_sources"]["status"] == "EXACT_FROZEN_INPUT"
            best = next(
                item["content"]
                for item in workspace["artifacts"]["candidates"]
                if item["asset_type"] == "best_draft_candidate"
            )
            assert (
                best["realization_contract"]["contract_version"]
                == "scene-realization-composition.v3"
            )
            assert best["realization_contract"]["craft_tasks"]["tasks"]
        if author_guided:
            from novel_forge.modules.chapter_outcome.acceptance_contract import resolve_accepted_manuscript
            from novel_forge.modules.story_design_authority.author_input import text_hash
            for workspace in workspaces["workspaces"]:
                manuscript = resolve_accepted_manuscript(workspace)
                candidate = manuscript["candidate"]["content"]
                guidance = candidate["author_design_guidance"]
                assert guidance["brief_asset_version_id"] == brief.asset_version_id
                assert guidance["brief_content_hash"] == brief.content_hash
                assert all(item["visibility"] == "SCENE_INTENT" for item in guidance["fragments"])
                assert "PRIVATE_AUTHOR_CAUSE_NOT_FOR_WRITER" not in json.dumps(guidance)
                assert all(text_hash(item["text"]) == item["content_hash"] for item in guidance["fragments"])
            contexts = AuthorityAssetQuery(DATABASE_URL).list_versions(project_id=harness.project_id, asset_type="context_bundle", limit=500)
            bound_contexts = [item for item in contexts if item.content.get("author_design_projection")]
            assert bound_contexts
            from novel_forge.modules.story_design_authority.author_input import compile_provider_author_projection
            for item in bound_contexts:
                manifest = item.content["context_manifest"]
                original = item.content["author_design_projection"]
                delivered = manifest["provider_context_view"]["compiled_view"]["author_design_projection"]
                assert delivered == compile_provider_author_projection(original)
                semantic_fields = {"text", "fragment_id", "content_hash", "visibility", "strength", "chapter_range"}
                assert delivered["fragments"] == [
                    {key: value for key, value in fragment.items() if key in semantic_fields}
                    for fragment in original["fragments"]
                ]
                assert delivered["source_receipt"]["json_pointer"] == "/author_design_projection"
                assert delivered["source_receipt"]["content_hash"] == canonical_hash(original)
                assert any(selected["logical_context_kind"] == "planning_author_design_projection" for selected in manifest["selected_inputs"])
        artifact = {
            "prepared": {"creation_input_policy": policy} if creative_validation else prepared,
            "opening": creation_result if creative_validation else opened,
            "ticks": {"status": "NOT_RECORDED"} if creative_validation else ticks,
            "workspaces": workspaces,
            "proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY",
            "formation": result,
            "provider_calls": transport.calls,
        }
        (tmp_path / "formation-production.json").write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, default=str)
        )
        from scripts.run_world_production_smoke import export, export_artifacts

        export_artifacts(
            database_url=DATABASE_URL,
            project_id=harness.project_id,
            destination=tmp_path,
            extra_kinds=(
                "planning_generation_candidate",
                "narrative_design_evaluation",
            ),
        )
        export(
            composition=composition,
            book_run_id=book_run.book_run_id,
            destination=tmp_path,
        )
        from scripts.compare_creation_exports import chapters
        from scripts.creation_pilot import prepare_pilot_book
        assert set(chapters(tmp_path)) == set(range(1, target_chapters + 1))
        assert len(list(tmp_path.glob("accepted-chapter-*.txt"))) == target_chapters
        if creative_validation:
            from copy import deepcopy
            from novel_forge.modules.chapter_quality_authority.creative_validation import verify_internal_quality
            reports = AuthorityAssetQuery(DATABASE_URL).list_versions(project_id=harness.project_id, asset_type="quality_score_report")
            assert reports
            for report in reports:
                admission = report.content["internal_admission"]
                assert admission["status"] == "INTERNAL_ADMITTED" and admission["literary_qualification"] == "NOT_RUN"
                assert report.content["gate"] not in {"PASSED", "PASSED_WITH_WARNINGS"}
                forged = deepcopy(admission)
                forged["observations"][0]["status"] = "QUALIFIED"
                with pytest.raises(ValueError, match="VALIDATION_QUALITY_ADMISSION_TAMPERED"):
                    verify_internal_quality(DATABASE_URL, forged, project_id=harness.project_id, book_id=harness.book_ids[0])
            return
        assert formation.find_by_key(project_id=harness.project_id, book_id=harness.book_ids[0], idempotency_key=formation_key)["formation_run_id"] == admitted.formation_run_id
        assert formation.find_by_key(project_id=harness.project_id, book_id=harness.book_ids[0], idempotency_key="different-key") is None
        assert composition.opening.find_by_key(project_id=harness.project_id, book_id=harness.book_ids[0], idempotency_key=f"{harness.project_id}:synthesis:opening")["opening_run_id"] == opening.opening_run_id
        pilot_project = harness.project_id + "-pilot"
        pilot_principal = replace(principal, project_scope=frozenset({pilot_project}), permissions=principal.permissions | {"project.authority.execute"})
        frozen_pilot = {"creation_policy": policy, "implementation_identity": RELEASE_SHA}
        arguments = dict(composition=composition, principal=pilot_principal, project_id=pilot_project,
                         workspace_id=pilot_project + "-workspace", book_id=pilot_project + "-book",
                         run_key=f"{harness.project_id}:pilot-prepare", title="隔离试运行", frozen=frozen_pilot)
        first_book = prepare_pilot_book(**arguments, initialize=True)
        assert prepare_pilot_book(**arguments, initialize=True) == first_book
        assert prepare_pilot_book(**arguments, initialize=False) == first_book
        with pytest.raises(ValueError, match="differs"):
            prepare_pilot_book(**{**arguments, "frozen": {**frozen_pilot, "run_key": "changed"}}, initialize=False)
    finally:
        if historical:
            historical.undo()
        (tmp_path / "provider-transcript.json").write_text(
            json.dumps(
                {
                    "proof_ceiling": "SCRIPTED_TRANSPORT_ONLY",
                    "foundation": transport.calls,
                    "chapter": transport.chapter.calls,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        execution.close()


def _recover_runtime_profile_formation(*, harness, chapter_pack, formation, principal, settings, env, registry, transport, admitted):
    from concurrent.futures import ThreadPoolExecutor
    from novel_forge.modules.command_kernel.budget_runtime import resolve_provider_budget_failure
    from novel_forge.modules.command_kernel.cancellation import CancelCommand, request_cancellation, resolve_cancellation
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.story_planning_runtime.application import _command_from_payload
    from novel_forge.modules.story_planning_runtime.runtime_continuation import require_binding

    assert not transport.calls
    failed = formation.require(admitted.formation_run_id)
    assert failed["lifecycle"] == "FAILED"
    assert failed["current_stage"] == "CREATIVE_SEARCH"
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT op.operation_id,op.version,op.status,op.command_payload->'payload',effect.external_effect_id,reservation.reservation_id,snapshot.snapshot_payload FROM authority_operation op JOIN authority_story_planning_generation generation USING(operation_id) JOIN authority_external_effect effect USING(operation_id) JOIN authority_budget_reservation reservation USING(operation_id) JOIN authority_attempt_capability_pack_snapshot snapshot USING(operation_id) WHERE op.project_id=%s", [harness.project_id])
        source_id, source_version, source_status, source_payload, effect_id, reservation_id, source_snapshot = uow.cursor.fetchone()
        assert source_status == "FAILED_RETRYABLE"
        assert source_payload["execution_contract_version"] == "1.15.0"
        uow.cursor.execute("SELECT count(*) FROM authority_external_effect_dispatch WHERE external_effect_id=%s", [effect_id])
        assert uow.cursor.fetchone()[0] == 0
    requested = request_cancellation(DATABASE_URL, CancelCommand(operation_id=source_id,project_id=harness.project_id,actor_id=principal.principal_id,expected_version=source_version,reason="fixture verified no dispatch before runtime repair",idempotency_key=f"{source_id}:cancel",trace_id="trace:runtime-continuation",correlation_id=harness.project_id))
    del requested
    def cancel():
        return resolve_cancellation(DATABASE_URL,operation_id=source_id,project_id=harness.project_id,expected_version=source_version+1,resolution="never_dispatched_effects",actor_id=principal.principal_id,reason="all reservations released and no dispatch",trace_id="trace:runtime-continuation",correlation_id=harness.project_id)
    with pytest.raises(KernelError, match="CANCELLATION_NOT_DISPATCHED_PROOF_REQUIRED"):
        cancel()
    assert resolve_provider_budget_failure(DATABASE_URL,reservation_id=reservation_id,project_id=harness.project_id)["status"] == "RELEASED"
    cancelled = cancel()
    assert cancel()["replayed"] is True
    new_sha = "f" * 40
    definition = story_planning_generation_definition(application_build_id="synthesis-formation", commit_sha=new_sha, definition_version="1.15.0")
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        registered = uow.repositories.definitions.register(definition)
        uow.cursor.execute("SELECT definition_hash FROM authority_operation_definition WHERE name=%s AND definition_version=%s",[definition["name"],definition["definition_version"]])
        digest=uow.cursor.fetchone()[0]
        uow.commit()
    del registered
    profile = build_story_planning_pack_profile(Path(__file__).resolve().parents[2], operation_definition_hash=digest,pack_id=harness.pack_id, execution_contract_version="1.15.0")
    harness._base_manifest,harness._base_catalog=profile.manifest,profile.artifact_catalog
    scope=harness.approval_scope(environments=("test",),runtime_profiles=("test",))
    scope["allowed_workflow_definition_refs"]=[profile.workflow_ref]
    from novel_forge.modules.capability_pack_authority.application import CapabilityPackAuthorityApplication
    harness.release_sha=new_sha
    harness.application=CapabilityPackAuthorityApplication(DATABASE_URL,application_build_id=harness.application_build_id,commit_sha=new_sha)
    approved=harness.register_compile_approve("1.2.0",generation=2,approval_scope=scope,target_runtime_profile="test",proof_skill_ref=profile.agent_skill_ref,release_sha=new_sha)
    deployment=harness.deploy(approved,environment="test",runtime_profile="test")
    harness.activate(deployment,expected_activation_version=1,environment="test")
    from novel_forge.modules.chapter_authority.definitions import chapter_operation_definitions
    from novel_forge.modules.agent_runtime.definitions import agent_runtime_operation_definitions
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        for item in (*chapter_operation_definitions(application_build_id=chapter_pack.application_build_id,commit_sha=new_sha,model_effects_required=True),
                     *chapter_operation_definitions(application_build_id=chapter_pack.application_build_id,commit_sha=new_sha,model_effects_required=True,coordinated_contract=True),
                     *agent_runtime_operation_definitions(application_build_id=chapter_pack.application_build_id,commit_sha=new_sha)):
            uow.repositories.definitions.register(item)
        uow.commit()
    chapter_pack.release_sha=new_sha
    chapter_pack.application=CapabilityPackAuthorityApplication(DATABASE_URL,application_build_id=chapter_pack.application_build_id,commit_sha=new_sha)
    approved_chapter=chapter_pack.register_compile_approve("1.1.0",generation=2,approval_scope=chapter_pack.approval_scope(environments=("test",),runtime_profiles=("test",)),target_runtime_profile="test",release_sha=new_sha)
    chapter_deployment=chapter_pack.deploy(approved_chapter,environment="test",runtime_profile="test")
    chapter_pack.activate(chapter_deployment,expected_activation_version=1,environment="test")
    env["NOVEL_FORGE_COMMIT_SHA"]=new_sha
    execution=build_production_execution_composition(settings,env=env,provider_registry=registry,planning_fixture_factory=transport.planning,chapter_fixture_factory=transport.chapter)
    chapter=build_chapter_authority_application(settings,execution=execution,env=env)
    composition=build_book_production_composition(settings,principal=principal,execution=execution,chapter_application=chapter,env=env)
    formation=composition.formation
    planning=formation.generation.planning
    def register():
        return planning.register_runtime_continuation(source_id,project_id=harness.project_id,principal=principal,expected_source_version=cancelled["version"],decision_evidence={"authorization_ref":"test:trusted-runtime-continuation", "authorized_reasoning_effort":"high", "reason":"exact immutable profile identity repair"},trace_id="trace:runtime-continuation",correlation_id=harness.project_id)
    worker = replace(principal, principal_type=__import__('novel_forge.modules.authority_security',fromlist=['PrincipalType']).PrincipalType.SERVICE)
    with pytest.raises(PermissionError):
        planning.register_runtime_continuation(source_id,project_id=harness.project_id,principal=worker,expected_source_version=cancelled["version"],decision_evidence={"authorization_ref":"test:trusted-runtime-continuation","reason":"not operator"},trace_id="trace:runtime-continuation",correlation_id=harness.project_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        registrations=list(pool.map(lambda _:register(),range(2)))
    assert {item["operation_id"] for item in registrations}.__len__()==1
    continuation_id=f"planning-runtime-continuation:{source_id}"
    binding=require_binding(DATABASE_URL,continuation_id)
    assert binding["source_command"]==source_payload
    assert binding["target_release_sha"]==new_sha
    assert binding["successor_command"]["execution_contract_version"]=="1.15.0"
    assert binding["successor_operation_id"] is None
    successor=_command_from_payload(binding["successor_command"])
    with pytest.raises(KernelError,match="PLANNING_RUNTIME_CONTINUATION_COMMAND_DRIFT"):
        planning.generate(replace(successor,book_id="different-book"),principal=replace(principal,principal_id=successor.actor_id))
    actual_sha=planning.commit_sha
    planning.commit_sha=RELEASE_SHA
    try:
        with pytest.raises(KernelError,match="PLANNING_RUNTIME_CONTINUATION_COMMAND_DRIFT"):
            planning.generate(successor,principal=replace(principal,principal_id=successor.actor_id))
    finally:
        planning.commit_sha=actual_sha
    formation.resume(admitted.formation_run_id,expected_version=failed["version"],principal=principal)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT status,command_payload->'payload' FROM authority_operation WHERE operation_id=%s",[source_id])
        assert uow.cursor.fetchone()==("CANCELLED",source_payload)
        uow.cursor.execute("SELECT snapshot_payload FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s",[source_id])
        assert uow.cursor.fetchone()[0]==source_snapshot
        uow.cursor.execute("SELECT status FROM authority_external_effect WHERE external_effect_id=%s",[effect_id])
        assert uow.cursor.fetchone()[0]=="CANCELLED"
    planning.generate(successor, principal=replace(principal, principal_id=successor.actor_id))
    definition = story_planning_generation_definition(application_build_id="synthesis-formation", commit_sha=new_sha)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.repositories.definitions.register(definition)
        uow.cursor.execute("SELECT definition_hash FROM authority_operation_definition WHERE name=%s AND definition_version=%s", [definition["name"], definition["definition_version"]])
        digest = uow.cursor.fetchone()[0]
        uow.commit()
    profile = build_story_planning_pack_profile(Path(__file__).resolve().parents[2], operation_definition_hash=digest, pack_id=harness.pack_id)
    harness._base_manifest, harness._base_catalog = profile.manifest, profile.artifact_catalog
    approved = harness.register_compile_approve("1.3.0", generation=3, approval_scope=scope, target_runtime_profile="test", proof_skill_ref=profile.agent_skill_ref, release_sha=new_sha)
    deployment = harness.deploy(approved, environment="test", runtime_profile="test")
    harness.activate(deployment, expected_activation_version=2, environment="test")
    return formation,execution


def _assert_runtime_continuation_once(formation, harness, transport, principal):
    from concurrent.futures import ThreadPoolExecutor
    from novel_forge.modules.story_planning_runtime.application import _command_from_payload
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT source_operation_id,successor_operation_id,source_command,target_release_sha,source_evidence_asset_version_id FROM authority_story_planning_runtime_continuation WHERE project_id=%s",[harness.project_id])
        rows=uow.cursor.fetchall()
        assert len(rows)==1
        source_id,successor_id,payload,target_sha,control_asset=rows[0]
        assert successor_id and source_id!=successor_id
        uow.cursor.execute("SELECT op.status,op.causation_operation_id,snapshot.release_sha,g.candidate_asset_version_id,g.input_snapshot_hash FROM authority_operation op JOIN authority_story_planning_generation g USING(operation_id) JOIN authority_attempt_capability_pack_snapshot snapshot USING(operation_id) WHERE op.operation_id=ANY(%s) ORDER BY op.status",[[source_id,successor_id]])
        source,successor=uow.cursor.fetchall()
        assert source[0]=="CANCELLED" and source[3] is None
        assert successor[0]=="SUCCEEDED" and successor[1]==source_id and successor[2]==target_sha
        assert source[2]!=target_sha and source[4]==successor[4]
        uow.cursor.execute("SELECT input_asset_snapshot FROM authority_operation WHERE operation_id=%s",[successor_id])
        assert all(item["asset_version_id"] != control_asset for item in uow.cursor.fetchone()[0])
    command=_command_from_payload(payload)
    worker=replace(principal,principal_id=command.actor_id)
    before=len(transport.calls)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(lambda version:formation.generation.planning.generate(replace(command,execution_contract_version=version),principal=worker),["1.15.0","1.17.0"]))
    assert len({item.candidate_asset_version_id for item in outcomes})==1
    assert all(item.generation_operation_id==successor_id for item in outcomes)
    assert len(transport.calls)==before


def test_native_unbound_foundation_uncertainty_repairs_without_rewriting_success(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(
        tmp_path, monkeypatch, False, False, False, False, False, False, 1,
        foundation_uncertainty_recovery=True,
    )


def test_creative_validation_native_controlled_process_to_internal_acceptance(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(
        tmp_path, monkeypatch, False, False, False, False, False, False, 1,
        creative_validation=True,
    )


def test_native_author_adoption_result_repair_and_legacy_receipt_replay(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(
        tmp_path, monkeypatch, True, False, False, False, False, False, 1,
        author_result_repair=True,
    )


def test_native_retained_valid_result_admission_without_another_provider_call(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(
        tmp_path, monkeypatch, False, False, False, False, False, False, 1,
        creative_validation=True, valid_result_admission=True,
    )


def _recover_capacity_formation(*, harness, chapter_pack, principal, pack_actor, settings, env, registry, transport, admitted, monkeypatch, routing=False, input_order=False,world_optional=False,stage_repairs=False,policy_upgrade=False):
    from concurrent.futures import ThreadPoolExecutor
    from novel_forge.modules.command_kernel.cancellation import CancelCommand, request_cancellation
    from novel_forge.modules.capability_packs.validation_deployment import register_validation_runtime_definitions, install_chapter_validation_pack
    from tests.integration.creative_validation_production_support import install_planning
    from novel_forge.modules.story_planning_runtime.runtime_continuation import require_binding
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT o.operation_id,o.version,o.command_payload->'payload' FROM authority_operation o JOIN authority_story_planning_generation g USING(operation_id) WHERE o.project_id=%s AND o.status=%s AND (NOT %s OR g.status='REJECTED' AND g.candidate_asset_version_id IS NOT NULL) ORDER BY g.created_at ASC", [harness.project_id,"FAILED_FINAL" if input_order or world_optional or stage_repairs else "FAILED_RETRYABLE",stage_repairs])
        row = uow.cursor.fetchone()
        source_status = "FAILED_RETRYABLE"
        if row is None and not (input_order or world_optional or stage_repairs):
            uow.cursor.execute("SELECT o.operation_id,o.version,o.command_payload->'payload' FROM authority_operation o JOIN authority_story_planning_generation g USING(operation_id) WHERE o.project_id=%s AND o.status='FAILED_FINAL' AND EXISTS (SELECT 1 FROM authority_attempt a WHERE a.operation_id=o.operation_id AND a.result->>'error_code'='PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED') ORDER BY g.created_at ASC", [harness.project_id])
            row = uow.cursor.fetchone()
            source_status = "FAILED_FINAL"
        assert row is not None
        source, version, original = row
        uow.cursor.execute("SELECT count(*) FROM authority_external_effect WHERE operation_id=%s", [source])
        assert uow.cursor.fetchone()[0] == (3 if stage_repairs else 2 if world_optional else 0)
    before = len(transport.calls)
    if input_order or world_optional or stage_repairs or source_status == "FAILED_FINAL":
        cancelled = {"status":"FAILED_FINAL" if input_order or world_optional or source_status == "FAILED_FINAL" else 'FAILED_RETRYABLE', "version":version}
    else:
        cancelled = request_cancellation(DATABASE_URL,CancelCommand(operation_id=source,project_id=harness.project_id,
            actor_id=principal.principal_id,expected_version=version,reason="native capacity successor; zero dispatch",
            idempotency_key=source+":capacity-cancel",trace_id=harness.project_id,correlation_id=harness.project_id),settle_undispatched=True)
        assert cancelled["status"] == "CANCELLED"
    sha = "f"*40
    hashes = register_validation_runtime_definitions(DATABASE_URL,application_build_id=harness.application_build_id,commit_sha=sha)
    harness.release_sha=sha
    if routing or world_optional or stage_repairs:
        from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
        from tests.unit.test_creative_execution_template import template
        value = template(harness.book_ids[0], version="creative-execution-template.v2", repair_routing={
            "version": "native-repair-routing.v1", "max_same_route_repairs": 2})
        value["allowed_candidates"] = ["codex-cli:gpt-test:high"]
        if world_optional:
            value.update(version='creative-execution-template.v3',world_future_preparation='DISABLED')
        if stage_repairs:
            value.update(version='creative-execution-template.v4',world_future_preparation='DISABLED',
                repair_routing={'version':'native-repair-routing.v2','max_same_route_repairs':2})
        configure_owned_policy(database_url=DATABASE_URL, owner="PROVIDER_ROUTING", project_id=harness.project_id,
            workspace_id=harness.workspace_id, principal=pack_actor, application_build_id=harness.application_build_id,
            commit_sha=sha, idempotency_key=harness.project_id+":repair-policy-v2", trace_id=harness.project_id,
            correlation_id=harness.project_id, content={"policy_version":"creative-e2e.v2", "task_overrides":[],
                "reason":"explicit successor for undispatched native repair", "execution_templates":[value]})
    if policy_upgrade:
        from novel_forge.modules.capability_packs.validation_deployment import install_longform_validation_pack
        profile = build_story_planning_pack_profile(Path(__file__).resolve().parents[2],
            operation_definition_hash=hashes["planning"], pack_id=harness.pack_id,
            semantic_context_compression=False)
        install_longform_validation_pack(DATABASE_URL, profile=profile, pack_version="1.2.0", agent_generation=2,
            expected_activation_version=1, project_id=harness.project_id, workspace_id=harness.workspace_id,
            book_id=harness.book_ids[0], application_build_id=harness.application_build_id, commit_sha=sha,
            compiler=pack_actor, approver=pack_actor, agent_admin=pack_actor, agent_domain="story_planning", agent_scope_type="BOOK")
    else:
        harness.pack_id += ".capacity"
        chapter_pack.pack_id += ".capacity"
        install_chapter_validation_pack(DATABASE_URL,repository_root=Path(__file__).resolve().parents[2],project_id=harness.project_id,
            workspace_id=harness.workspace_id,book_id=harness.book_ids[0],application_build_id=harness.application_build_id,commit_sha=sha,
            compiler=pack_actor,approver=pack_actor,agent_admin=pack_actor,pack_id_override=chapter_pack.pack_id)
        profile=build_story_planning_pack_profile(Path(__file__).resolve().parents[2],operation_definition_hash=hashes["planning"],
            pack_id=harness.pack_id,planning_task_token_budget=None if routing else 128000)
        install_planning(harness,profile,pack_actor)
    env.update(NOVEL_FORGE_COMMIT_SHA=sha,NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID=harness.pack_id,NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID=chapter_pack.pack_id)
    execution=build_production_execution_composition(settings,env=env,provider_registry=registry,planning_fixture_factory=transport.planning,chapter_fixture_factory=transport.chapter)
    chapter=build_chapter_authority_application(settings,execution=execution,env=env)
    composition=build_book_production_composition(settings,principal=principal,execution=execution,chapter_application=chapter,env=env)
    formation=composition.formation
    planning=formation.generation.planning
    if world_optional or stage_repairs:
        return formation,execution,chapter,composition
    def register():
        return planning.register_runtime_continuation(source,project_id=harness.project_id,principal=principal,
            expected_source_version=cancelled["version"],decision_evidence={"authorization_ref":"member-grant",
                "authorized_reasoning_effort":"high","reason":"same task and repair count; capacity only"},trace_id=harness.project_id,correlation_id=harness.project_id)
    from novel_forge.modules.story_planning_runtime import preflight_continuation
    from novel_forge.modules.command_kernel.errors import KernelError
    if not policy_upgrade:
        with monkeypatch.context() as strict:
            verified=preflight_continuation.verify_template_provenance
            strict.setattr(preflight_continuation,"verify_template_provenance",lambda *args: {**verified(*args),"mode":"STRICT_PRODUCTION"})
            with pytest.raises(KernelError,match="PLANNING_RUNTIME_CONTINUATION_FAILURE_NOT_ALLOWED" if routing and not input_order else "PLANNING_RUNTIME_CONTINUATION_POLICY_REQUIRED"):
                register()
    with ThreadPoolExecutor(max_workers=2) as pool:
        records=list(pool.map(lambda _:register(),range(2)))
    assert len({r["operation_id"] for r in records})==1 and len(transport.calls)==before
    binding=require_binding(DATABASE_URL,records[0]["continuation_id"])
    assert binding["source_command"]==original
    if policy_upgrade:
        allocation = binding["target_runtime"]["planning_capacity"]
        assert allocation["capacity_policy_upgrade"]["contract_version"] == "complete-request-capacity-upgrade.v1"
        assert allocation["context_revalidation"]["contract_version"] == "complete-request-capacity-context.v1"
        from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
        frozen = AuthorityAssetQuery(DATABASE_URL).require(project_id=harness.project_id,
            asset_version_id=allocation["context_revalidation"]["context_asset_version_id"])
        assert frozen.content["planning_context_policy_version"] == "context-policy:chapter-generation-pack:v2"
    assert binding["successor_command"]["repair_number"]==original["repair_number"]==(2 if input_order else 1)
    if not routing:
        failed=formation.require(admitted.formation_run_id)
        formation.resume(admitted.formation_run_id,expected_version=failed["version"],principal=principal)
    return formation,execution,chapter,composition


def test_native_undispatched_result_repair_capacity_successor_preserves_raw_task(tmp_path,monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(tmp_path,monkeypatch,author_guided=True,
        result_repair=False,runtime_recovery=False,evaluation_recovery=False,manual_review=False,advice_only=False,
        target_chapters=1,creative_validation=True,author_result_repair=True,capacity_continuation=True,capacity_policy_upgrade=True)


def test_native_bounded_semantic_repair_reaches_review_acceptance_and_replays_without_calls(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(tmp_path, monkeypatch, False,
        False, False, False, False, False, 1, creative_validation=True, semantic_repair=True)


def test_native_undispatched_route_repair_successor_preserves_candidate_counter_and_acceptance(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(tmp_path, monkeypatch, False,
        False, False, False, False, False, 1, creative_validation=True, semantic_repair=True,
        route_continuation=True)


def test_native_failed_final_input_order_successor_preserves_terminal_history_and_counter(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(tmp_path, monkeypatch, False,
        False, False, False, False, False, 1, creative_validation=True, semantic_repair=True,
        input_order_continuation=True)


def test_native_world_raw_result_repair_preserves_world_source_and_reaches_acceptance(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(tmp_path, monkeypatch,
        False, False, False, False, False, False, 1, creative_validation=True, world_result_repair=True)


def test_native_world_identifier_checkpoint_recovers_settled_effect_without_resend(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(tmp_path, monkeypatch,
        False, False, False, False, False, False, 1, creative_validation=True, world_result_repair="reference-checkpoint")


def test_native_disabled_world_future_reaches_review_acceptance_without_simulation(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(tmp_path, monkeypatch,
        False, False, False, False, False, False, 1, creative_validation=True, world_disabled=True)


def test_native_settled_optional_world_failure_continues_without_repeating_calls(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(tmp_path, monkeypatch,
        False, False, False, False, False, False, 1, creative_validation=True, world_optional_recovery=True)


def test_native_rejected_null_schema_result_revalidates_without_resend_then_accepts(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(tmp_path, monkeypatch,
        False, False, False, False, False, False, 1, creative_validation=True, world_disabled=True, gateway_null_recovery=True)


@pytest.mark.parametrize("entry", ["generate", "scan", "cancel-race"])
def test_native_completed_planning_release_recovery_preserves_retryable_history(tmp_path, monkeypatch, entry):
    test_native_formation_generates_foundation_from_author_brief(tmp_path, monkeypatch,
        False, False, False, False, False, False, 1, creative_validation=True, world_disabled=True, completed_release_recovery=entry)


def test_native_world_repairs_do_not_exhaust_rejected_chapter_plan_stage(tmp_path,monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(tmp_path,monkeypatch,
        False,False,False,False,False,False,1,creative_validation=True,world_result_repair=True,
        gateway_null_recovery=True,stage_repair_recovery=True)


def test_native_started_memo_timeout_is_unknown_and_refuses_new_send(tmp_path,monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(tmp_path,monkeypatch,
        author_guided=False,result_repair=False,runtime_recovery=False,evaluation_recovery=False,manual_review=False,advice_only=False,target_chapters=1,
        complete_after_result_repair=True,creative_validation=True,world_disabled=True,memo_timeout_recovery=True)


def test_native_scene_core_successor_reuses_memo_and_preserves_failed_step(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(tmp_path, monkeypatch,
        author_guided=False, result_repair=False, runtime_recovery=False, evaluation_recovery=False,
        manual_review=False, advice_only=False, target_chapters=1,
        complete_after_result_repair=True, creative_validation=True, world_disabled=True, scene_core_recovery=True)


def test_native_information_flow_repairs_settled_candidate_and_preserves_usage(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(tmp_path, monkeypatch,
        author_guided=False, result_repair=False, runtime_recovery=False, evaluation_recovery=False,
        manual_review=False, advice_only=False, target_chapters=1,
        complete_after_result_repair=True, creative_validation=True, world_disabled=True, scene_information_recovery=True)


def test_native_review_scope_successor_retains_rejected_review_and_accepts(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(tmp_path, monkeypatch,
        author_guided=False, result_repair=False, runtime_recovery=False, evaluation_recovery=False,
        manual_review=False, advice_only=False, target_chapters=1,
        complete_after_result_repair=True, creative_validation=True, world_disabled=True, review_knowledge_recovery=True)


def test_native_length_scope_successor_preserves_failed_revision_and_accepts(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(tmp_path, monkeypatch,
        author_guided=False, result_repair=False, runtime_recovery=False, evaluation_recovery=False,
        manual_review=False, advice_only=False, target_chapters=1,
        complete_after_result_repair=True, creative_validation=True, world_disabled=True, length_scope_recovery=True)


def test_native_started_memo_timeout_blocks_exhaustion_and_successor(tmp_path, monkeypatch):
    test_native_formation_generates_foundation_from_author_brief(tmp_path,monkeypatch,
        author_guided=False,result_repair=False,runtime_recovery=False,evaluation_recovery=False,
        manual_review=False,advice_only=False,target_chapters=1,complete_after_result_repair=True,
        creative_validation=True,world_disabled=True,memo_timeout_prefix_recovery=True)
