from __future__ import annotations

from novel_forge.modules.capability_packs.validation_deployment import (
    install_chapter_validation_pack,
    install_longform_validation_pack,
    register_validation_runtime_definitions,
)
from novel_forge.modules.capability_packs.longform_profiles import (
    build_longform_prose_review_pack_profile,
    build_narrative_evaluation_pack_profile,
    build_reader_outcome_pack_profile,
    build_story_planning_pack_profile,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.capability_pack_postgres_support import (
    ROOT,
    CapabilityPackPostgresHarness,
)


def test_quality_validation_packs_deploy_to_one_exact_book_scope() -> None:
    harness = CapabilityPackPostgresHarness("quality-validation-deployment")
    hashes = register_validation_runtime_definitions(
        DATABASE_URL,
        application_build_id=harness.application_build_id,
        commit_sha=harness.release_sha,
    )
    common = {
        "project_id": harness.project_id,
        "workspace_id": harness.workspace_id,
        "book_id": harness.book_ids[0],
        "application_build_id": harness.application_build_id,
        "commit_sha": harness.release_sha,
        "compiler": harness.compiler,
        "approver": harness.approver,
        "agent_admin": harness.agent_admin,
    }
    planning_id = f"{harness.pack_id}-planning"
    reader_id = f"{harness.pack_id}-reader"
    prose_id = f"{harness.pack_id}-prose"
    evaluator_id = f"{harness.pack_id}-evaluator"
    chapter_id = f"{harness.pack_id}-chapter"
    evaluator = install_longform_validation_pack(
        DATABASE_URL,
        profile=build_narrative_evaluation_pack_profile(
            ROOT,
            operation_definition_hash=hashes["narrative_evaluation"],
            pack_id=evaluator_id,
        ),
        pack_version="1.0.0",
        agent_generation=1,
        expected_activation_version=0,
        agent_domain="story_design",
        agent_scope_type="BOOK",
        **common,
    )
    planning = install_longform_validation_pack(
        DATABASE_URL,
        profile=build_story_planning_pack_profile(
            ROOT,
            operation_definition_hash=hashes["planning"],
            pack_id=planning_id,
        ),
        pack_version="1.0.0",
        agent_generation=1,
        expected_activation_version=0,
        agent_domain="story_planning",
        agent_scope_type="BOOK",
        **common,
    )
    reader = install_longform_validation_pack(
        DATABASE_URL,
        profile=build_reader_outcome_pack_profile(
            ROOT,
            operation_definition_hash=hashes["reader_proxy"],
            pack_id=reader_id,
        ),
        pack_version="1.0.0",
        agent_generation=1,
        expected_activation_version=0,
        agent_domain="reader_outcome",
        agent_scope_type="CHAPTER",
        **common,
    )
    prose = install_longform_validation_pack(
        DATABASE_URL,
        profile=build_longform_prose_review_pack_profile(
            ROOT,
            operation_definition_hash=hashes["prose_review"],
            pack_id=prose_id,
        ),
        pack_version="1.1.0",
        agent_generation=1,
        expected_activation_version=0,
        agent_domain="book_followup",
        agent_scope_type="BOOK",
        **common,
    )
    chapter = install_chapter_validation_pack(
        DATABASE_URL,
        repository_root=ROOT,
        pack_id_override=chapter_id,
        pack_version_override="1.0.0",
        **common,
    )

    installed = (evaluator, planning, reader, prose, chapter)
    assert {item["pack_id"] for item in installed} == {
        evaluator_id,
        planning_id,
        reader_id,
        prose_id,
        chapter_id,
    }
    assert all(item["manifest_hash"].startswith("sha256:") for item in installed)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT deployment.pack_id, deployment.deployment_status,
                   deployment.project_id, deployment.workspace_id,
                   deployment.book_id, compilation.release_sha
            FROM authority_capability_pack_activation AS activation
            JOIN authority_capability_pack_deployment AS deployment
              ON deployment.deployment_id=activation.active_deployment_id
            JOIN authority_capability_pack_compilation AS compilation
              ON compilation.compilation_id=deployment.compilation_id
            WHERE activation.target_scope_type='BOOK'
              AND activation.project_id=%s AND activation.workspace_id=%s
              AND activation.book_id=%s
              AND deployment.pack_id=ANY(%s)
            """,
            [
                harness.project_id,
                harness.workspace_id,
                harness.book_ids[0],
                [item["pack_id"] for item in installed],
            ],
        )
        rows = uow.cursor.fetchall()
    assert len(rows) == 5
    assert all(
        status == "ACTIVE"
        and project_id == harness.project_id
        and workspace_id == harness.workspace_id
        and book_id == harness.book_ids[0]
        and release_sha == harness.release_sha
        for _pack_id, status, project_id, workspace_id, book_id, release_sha in rows
    )


def test_chapter_sampling_pack_uses_separate_native_definitions_and_approval_scope() -> None:
    harness = CapabilityPackPostgresHarness("chapter-sampling-deployment")
    register_validation_runtime_definitions(
        DATABASE_URL, application_build_id=harness.application_build_id, commit_sha=harness.release_sha,
    )
    result = install_chapter_validation_pack(
        DATABASE_URL, repository_root=ROOT, project_id=harness.project_id,
        workspace_id=harness.workspace_id, book_id=harness.book_ids[0],
        application_build_id=harness.application_build_id, commit_sha=harness.release_sha,
        compiler=harness.compiler, approver=harness.approver, agent_admin=harness.agent_admin,
        pack_id_override=harness.pack_id, provider_sampling=True,
    )
    assert result["pack_id"] == harness.pack_id + ".provider_sampling"
    nodes = result["compilation"]["compiled"]["workflow_nodes"]
    assert {node["node_id"] for node in nodes} == {"memo", "draft", "revision", "canon_extraction"}
    assert all(node["definition_name"].startswith("chapter.provider.sample.") for node in nodes)
    assert all(node["authoritative_completion_contract"]["required_asset_selectors"][0]["eligibility"] == "INELIGIBLE" for node in nodes)
