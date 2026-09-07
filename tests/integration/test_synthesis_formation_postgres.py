from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json

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
)
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
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.workers.book_authority import execute_story_formation_claim
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.capability_pack_postgres_support import (
    CapabilityPackPostgresHarness,
    RELEASE_SHA,
)
from tests.integration.synthesis_production_support import SynthesisTransport
from tests.integration.test_core_functional_loops_postgres import _principal


def test_native_formation_generates_foundation_from_author_brief(tmp_path):
    harness = CapabilityPackPostgresHarness("synthesis-formation")
    from copy import copy

    chapter_pack = copy(harness)
    chapter_pack.pack_id += "-chapter"
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
    definition = story_planning_generation_definition(
        application_build_id="synthesis-formation", commit_sha=RELEASE_SHA
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
    )
    harness._base_manifest, harness._base_catalog = (
        profile.manifest,
        profile.artifact_catalog,
    )
    approval = harness.approval_scope(
        environments=("test",), runtime_profiles=("test",)
    )
    approval["allowed_workflow_definition_refs"] = [profile.workflow_ref]
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
    brief = content.execute(
        ContentOperationRequest(
            definition_name="creative.brief.create",
            project_id=harness.project_id,
            workspace_id=harness.workspace_id,
            actor_id=principal.principal_id,
            trace_id="trace:synthesis-brief",
            correlation_id=harness.project_id,
            idempotency_key="synthesis:brief",
            payload={
                "brief": {
                    "creative_brief_contract_version": "creative-brief-v2",
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
    transport = SynthesisTransport()
    registry.register(transport)
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
        admitted = formation.admit(
            StartStoryFormationCommand(
                project_id=harness.project_id,
                workspace_id=harness.workspace_id,
                book_id=harness.book_ids[0],
                actor_id=principal.principal_id,
                expected_book_version=1,
                stable_idempotency_key="synthesis:formation",
                trace_id="trace:synthesis-formation",
                correlation_id=harness.project_id,
                frozen_input=StoryFormationInput(
                    creative_brief_asset_version_id=brief.asset_version_id,
                    creative_brief_content_hash=brief.content_hash,
                    generation_policy={
                        "contract_version": "formation-generation.v1",
                        "approval_mode": "AUTO",
                        "creative_candidates": 2,
                        "target_chapters": 3,
                        "title": "Witness Map",
                    },
                ),
            ),
            principal=principal,
        )
        for _ in range(10):
            formation.schedule_candidates(limit=1)
            claim = formation.runtime_jobs.claim(
                runtime_group="story_formation",
                worker_id="synthesis-worker",
                lease_seconds=60,
                job_kinds=("STORY_FORMATION_ADVANCE",),
                project_id=harness.project_id,
            )
            if claim is None:
                break
            execute_story_formation_claim(
                formation.runtime_jobs, formation, principal, claim, lease_seconds=60
            )
            if formation.require(admitted.formation_run_id)["lifecycle"] == "READY":
                break
        result = formation.require(admitted.formation_run_id)
        assert result["lifecycle"] == "READY", result
        assert len(transport.calls) == 7
        assert {call["stage"] for call in transport.calls} == {
            "creative.candidates.generate",
            "theme.candidates.generate",
            "ending.intent.generate",
            "reader.promise.generate",
            "world.design.generate",
            "character.cast.generate",
        }
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
                / "config/production/short-arc-creation.json"
            ).read_text()
        )
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
            idempotency_key="synthesis:opening",
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
        from scripts.run_world_production_smoke import drive, start_command
        from novel_forge.modules.authority_security import PrincipalType
        import time

        book_run = composition.authority.start(
            start_command(
                snapshot,
                actor=principal.principal_id,
                run_key="synthesis:production",
                chapters=3,
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
        assert stop == "ACCEPTED_TARGET_REACHED", (stop, ticks[-3:])
        from tests.integration.creative_grounding_support import (
            verify_creative_workspace,
        )

        workspaces = verify_creative_workspace(
            composition=composition,
            chapter_application=chapter,
            book_run_id=book_run.book_run_id,
            transport=transport.chapter,
        )
        artifact = {
            "prepared": prepared,
            "opening": opened,
            "ticks": ticks,
            "workspaces": workspaces,
            "proof_ceiling": "SCRIPTED_PROVIDER_PRODUCTION_WIRING_ONLY",
            "formation": result,
            "provider_calls": transport.calls,
        }
        (tmp_path / "formation-production.json").write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, default=str)
        )
    finally:
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
