from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

from psycopg.types.json import Jsonb
import pytest

from novel_forge.api import authority_dependencies
from novel_forge.api.authority_dependencies import (
    build_book_production_composition,
    build_chapter_authority_application,
    build_production_execution_composition,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_authority import OpenBookProductionRequest
from novel_forge.modules.book_authority.production import StartBookProductionCommand
from novel_forge.modules.chapter_quality_authority import (
    PostgresQualityQualificationAuthority,
)
from novel_forge.modules.reader_calibration import EvaluatorIdentityClass
from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.modules.runtime_proof import (
    BoundedQualityCampaignRunner,
    HumanReviewerTarget,
    PostgresBoundedQualityCampaignRuntime,
    load_quality_campaign_profile,
)
from novel_forge.modules.runtime_proof.quality_campaign import (
    bounded_quality_chapter_fixture_response,
    bounded_quality_planning_fixture_response,
)
from novel_forge.modules.story_planning_runtime import GENERATOR_INPUT_ROLES
from novel_forge.modules.story_planning_runtime import canonical_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.workers.book_authority import execute_book_opening_claim
from tests.integration.authority_postgres_support import DATABASE_URL, transaction
from tests.integration.capability_pack_postgres_support import (
    CapabilityPackPostgresHarness,
)
from tests.integration.test_core_functional_loops_postgres import (
    RELEASE_SHA,
    _activate_planning_pack,
    _principal,
    _seed_inputs,
)
from tests.integration import (
    test_postgresql_only_chapter_slice as chapter_slice_fixture,
)


MIGRATION_HEAD = "20260826_0101_quality_qualification"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_SCRIPTED_SEMANTIC_EVIDENCE_HASH = (
    "sha256:092b3642a3d060e3b7b5ab6ec74abb1a9bf33152c8bd666c70d1ed9079c12bcd"
)


def _hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _json_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {
            *(str(key).lower() for key in value),
            *(key for item in value.values() for key in _json_keys(item)),
        }
    if isinstance(value, list):
        return {key for item in value for key in _json_keys(item)}
    return set()


def _quality_principal(project_id: str) -> Principal:
    base = _principal(project_id)
    return Principal(
        principal_id=base.principal_id,
        principal_type=base.principal_type,
        permissions=frozenset(
            {
                *base.permissions,
                "quality.qualification.manage",
                "quality.qualification.query",
            }
        ),
        project_scope=base.project_scope,
        authentication_source="bounded-quality-campaign-integration",
    )


def _worker_principal(operator: Principal) -> Principal:
    return Principal(
        principal_id=f"bounded-quality-worker:{operator.principal_id}",
        principal_type=PrincipalType.WORKER,
        permissions=frozenset(
            permission
            for permission in operator.permissions
            if permission != "book.authority.approve_replan"
        ),
        project_scope=operator.project_scope,
        authentication_source="bounded-quality-campaign-worker",
    )


def _seed_reader_and_release_inputs(project_id: str, book_id: str) -> None:
    chapter_slice_fixture.PostgreSQLOnlyChapterSliceTests.release_evidence(project_id)
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE authority_asset_version
            SET lifecycle='SUPERSEDED'
            WHERE asset_version_id=%s
            """,
            [f"{project_id}:platform-profile-v1"],
        )
        cursor.execute(
            """
            INSERT INTO authority_asset(asset_id,project_id,asset_type)
            VALUES (%s,%s,'approval_decision')
            """,
            [f"fixture:{project_id}:approval-decision", project_id],
        )
        cursor.execute(
            """
            INSERT INTO authority_asset_version(
                asset_version_id,asset_id,version_number,lifecycle,
                eligibility,governance,content,content_hash,schema_version
            )
            SELECT %s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',
                   content,content_hash,'integration-fixture.v1'
            FROM authority_asset_version
            WHERE asset_version_id=%s
            """,
            [
                f"fixture:{project_id}:approval-decision:v1",
                f"fixture:{project_id}:approval-decision",
                f"{project_id}:approval-v1",
            ],
        )
        for asset_type in ("reader_segment_profile", "reader_contract"):
            asset_id = f"fixture:{project_id}:quality:{asset_type}"
            version_id = f"{asset_id}:v1"
            content = {
                "book_id": book_id,
                "role": asset_type,
                "profile_version": "reader-outcome-v3",
            }
            cursor.execute(
                """
                INSERT INTO authority_asset(asset_id,project_id,asset_type)
                VALUES (%s,%s,%s)
                """,
                [asset_id, project_id, asset_type],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id,asset_id,version_number,lifecycle,
                    eligibility,governance,content,content_hash,schema_version
                ) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,%s)
                """,
                [
                    version_id,
                    asset_id,
                    Jsonb(content),
                    canonical_hash(content),
                    f"{asset_type}.v1",
                ],
            )


def _planning_pack_hash(deployment_id: str) -> str:
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT version.manifest_hash
            FROM authority_capability_pack_deployment AS deployment
            JOIN authority_capability_pack_version AS version
              ON version.pack_id=deployment.pack_id
             AND version.pack_version=deployment.pack_version
            WHERE deployment.deployment_id=%s
            """,
            [deployment_id],
        )
        row = uow.cursor.fetchone()
    assert row is not None
    return str(row[0])


def _scripted_pack_manifest(
    *, profile_digest: str, planning_deployment_id: str
) -> dict[str, dict[str, str]]:
    return {
        "planning": {
            "deployment_id": planning_deployment_id,
            "hash": _planning_pack_hash(planning_deployment_id),
        },
        **{
            role: {
                "deployment_id": f"scripted-unpacked:{role}:v1",
                "hash": _hash(
                    {
                        "role": role,
                        "profile_digest": profile_digest,
                        "execution_class": "SCRIPTED_FIXTURE",
                    }
                ),
            }
            for role in ("chapter", "reader_proxy", "narrative_evaluation")
        },
    }


def test_scripted_bounded_quality_campaign_uses_canonical_two_by_four_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        authority_dependencies,
        "planning_fixture_response",
        bounded_quality_planning_fixture_response,
    )
    monkeypatch.setattr(
        authority_dependencies,
        "default_chapter_fixture_response",
        bounded_quality_chapter_fixture_response,
    )
    harness = CapabilityPackPostgresHarness("bounded-quality-campaign")
    planning_deployment_id = _activate_planning_pack(harness)
    project_id = harness.project_id
    workspace_id = harness.workspace_id
    book_id = harness.book_ids[0]
    generic = _seed_inputs(project_id, book_id, target_chapter_count=8)
    _seed_reader_and_release_inputs(project_id, book_id)
    operator = _quality_principal(project_id)
    worker = _worker_principal(operator)
    profile = load_quality_campaign_profile(
        REPOSITORY_ROOT / "config/proof_campaigns/quality_qualification_v1.json",
        repository_root=REPOSITORY_ROOT,
    )

    with tempfile.TemporaryDirectory(prefix="bounded-quality-campaign-") as root:
        settings = IndustrialSettings(
            root=REPOSITORY_ROOT,
            environment="development",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
        env = {
            "NOVEL_FORGE_ENVIRONMENT": "test",
            "NOVEL_FORGE_TEST_ALLOW_SCRIPTED_NARRATIVE_EVALUATION_FIXTURE": "true",
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "bounded-quality-campaign",
            "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
            "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_PLANNING_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_PLANNING_MODEL": "scripted-quality-campaign-v1",
            "NOVEL_FORGE_PLANNING_REASONING_EFFORT": "high",
            "NOVEL_FORGE_DRAFT_MODEL": "scripted-quality-campaign-v1",
            "NOVEL_FORGE_REVIEW_MODEL": "scripted-quality-campaign-v1",
            "NOVEL_FORGE_REVISION_MODEL": "scripted-quality-campaign-v1",
            "NOVEL_FORGE_REREVIEW_MODEL": "scripted-quality-campaign-v1",
            "NOVEL_FORGE_CANON_EXTRACTION_MODEL": "scripted-quality-campaign-v1",
            "NOVEL_FORGE_QUALITY_MODEL": "scripted-quality-campaign-v1",
            "NOVEL_FORGE_READER_OUTCOME_MODEL": "scripted-quality-campaign-v1",
            "NOVEL_FORGE_NARRATIVE_EVALUATOR_MODEL": ("scripted-quality-campaign-v1"),
            "NOVEL_FORGE_REASONING_EFFORT": "high",
            "NOVEL_FORGE_NARRATIVE_SEMANTIC_EVALUATION_REASONING_EFFORT": ("high"),
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": root,
            "NOVEL_FORGE_AUTHORITY_WORKER_ID": "bounded-quality-worker",
            "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": harness.pack_id,
        }
        execution = build_production_execution_composition(settings, env=env)
        chapter_application = build_chapter_authority_application(
            settings,
            execution=execution,
            env=env,
        )
        composition = build_book_production_composition(
            settings,
            principal=operator,
            execution=execution,
            env=env,
            chapter_application=chapter_application,
        )
        opening_roles = {
            role
            for generator in (
                "book_plan.generate",
                "volume_plan.generate",
                "arc_plan.generate",
            )
            for role in GENERATOR_INPUT_ROLES[generator]
            if role not in {"book_plan", "volume_plan"}
        }
        composition.open_book(
            OpenBookProductionRequest(
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=book_id,
                actor_id=operator.principal_id,
                expected_book_version=int(generic["book_version"]),
                production_profile=generic["production_profile"],
                planning_input_versions={role: generic[role] for role in opening_roles},
                arc_logical_keys=("arc:bounded-primary",),
                idempotency_key=f"{project_id}:bounded-quality:open",
                trace_id=f"trace:{project_id}:bounded-quality:open",
                correlation_id=f"correlation:{project_id}",
                initial_story_state_version=generic["initial_story_state"],
                initial_canon_snapshot_version=generic["initial_canon_snapshot"],
            )
        )
        assert composition.opening is not None
        runtime_jobs = RuntimeJobAuthority(DATABASE_URL)
        opening_claim = runtime_jobs.claim(
            runtime_group="book_opening",
            worker_id="bounded-quality-opening-worker",
            lease_seconds=30,
            job_kinds=("BOOK_OPENING_EXECUTE",),
            project_id=project_id,
        )
        assert opening_claim is not None
        opened = execute_book_opening_claim(
            runtime_jobs,
            composition.opening,
            operator,
            opening_claim,
            lease_seconds=30,
        )
        snapshot = composition.input_resolver.require(opened["input_snapshot_id"])
        assert len(opened["arc_plan_versions"]) == 1

        campaign_id = f"quality-campaign:{project_id}:scripted-v1"
        manifest = profile.freeze_manifest(
            campaign_id=campaign_id,
            exact_release_sha=RELEASE_SHA,
            migration_head=MIGRATION_HEAD,
            mode="scripted",
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            capability_pack_manifest=_scripted_pack_manifest(
                profile_digest=profile.digest,
                planning_deployment_id=planning_deployment_id,
            ),
            foundation_lineage={
                "foundation_set_digest": generic["foundation_set_digest"],
                "story_formation_run_id": generic["story_formation_run"],
                "book_design_asset_version_id": generic["book_design"],
                "book_version": generic["book_version"],
            },
            planning_lineage={
                "input_snapshot_id": snapshot.snapshot_id,
                "book_plan_asset_version_id": opened["book_plan_version"],
                "volume_plan_asset_version_id": opened["volume_plan_version"],
                "arc_plan_asset_version_ids": opened["arc_plan_versions"],
            },
            realization_lineage={
                "contract": "narrative-realization-v1",
                "expected_chapter_group_ranges": [[1, 4], [5, 8]],
                "binding_policy": "QUALIFICATION_FROZEN_BEFORE_EXECUTION",
            },
        )
        quality = PostgresQualityQualificationAuthority(
            DATABASE_URL,
            application_build_id="bounded-quality-campaign",
            commit_sha=RELEASE_SHA,
        )
        admitted = quality.admit_campaign(
            manifest,
            stable_idempotency_key=f"{campaign_id}:admit",
            trace_id=f"trace:{campaign_id}:admit",
            correlation_id=campaign_id,
            principal=operator,
        )
        assert admitted["lifecycle"] == "DRAFT"
        quality.freeze_campaign(campaign_id, expected_version=0, principal=operator)
        quality.start_campaign(campaign_id, expected_version=1, principal=operator)

        book = composition.authority.start(
            StartBookProductionCommand(
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=book_id,
                actor_id=operator.principal_id,
                trace_id=f"trace:{project_id}:bounded-quality:start",
                correlation_id=f"correlation:{project_id}",
                stable_idempotency_key=f"{project_id}:bounded-quality:start",
                book_design_version=snapshot.book_design_version,
                book_plan_version=snapshot.book_plan_version,
                production_profile_version=snapshot.production_profile_version,
                longform_context_versions={
                    "volume_plan_version": snapshot.current_volume_plan_version,
                    "arc_plan_versions": list(
                        snapshot.current_relevant_arc_plan_versions
                    ),
                    "character_state_version": snapshot.character_state_version,
                    "foreshadowing_state_version": (
                        snapshot.foreshadowing_state_version
                    ),
                    "quality_trend_version": snapshot.quality_trend_version,
                    "reward_ledger_version": snapshot.reward_ledger_version,
                    "promise_ledger_version": snapshot.promise_ledger_version,
                    "reader_segment_version": snapshot.reader_segment_version,
                    "reader_contract_version": snapshot.reader_contract_version,
                    "platform_profile_version": snapshot.platform_profile_version,
                },
                target_chapter_count=8,
                input_mode="RESOLVED_AUTHORITY_INPUT",
                input_snapshot_id=snapshot.snapshot_id,
                light_recap_cadence=4,
                formal_recap_cadence=8,
            ),
            principal=operator,
        )
        reviewers = (
            HumanReviewerTarget(
                "bounded-human-reviewer-1",
                EvaluatorIdentityClass.PROFESSIONAL_EDITOR,
            ),
            HumanReviewerTarget(
                "bounded-human-reviewer-2",
                EvaluatorIdentityClass.EXPERIENCED_READER,
            ),
        )

        def campaign_runtime(*, failure_injector=None):  # type: ignore[no-untyped-def]
            return PostgresBoundedQualityCampaignRuntime(
                database_url=DATABASE_URL,
                profile=profile,
                campaign_id=campaign_id,
                book_run_id=book.book_run_id,
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=book_id,
                primary_arc_plan_version_id=opened["arc_plan_versions"][0],
                volume_scope_id="volume:1:chapters:1-8",
                composition=composition,
                chapter_application=chapter_application,
                operator=operator,
                chapter_worker=worker,
                quality_authority=quality,
                reviewers=reviewers,
                campaign_secret="bounded-quality-campaign-secret-v1",
                mode="scripted",
                failure_injector=failure_injector,
            )

        runner = BoundedQualityCampaignRunner(profile, mode="scripted")
        result = runner.run(campaign_runtime())
        for failure_stage in (
            "after_acceptance:4",
            "after_receipt:4",
            "after_candidate_materialization",
            "after_pack_export",
        ):
            remaining = {"count": 1}

            def inject(stage: str, *, expected: str = failure_stage) -> None:
                if stage == expected and remaining["count"]:
                    remaining["count"] -= 1
                    raise RuntimeError(f"injected {stage}")

            with pytest.raises(RuntimeError, match=failure_stage):
                runner.run(campaign_runtime(failure_injector=inject))
            recovered = runner.run(campaign_runtime())
            assert recovered.semantic_identity == result.semantic_identity
        execution.close()

    assert result.accepted_chapters == tuple(range(1, 9))
    assert result.chapter_group_ranges == ((1, 4), (5, 8))
    assert result.accepted_through_chapter == 8
    assert result.blind_pack_count == 2
    assert result.provider_dispatch_count > 0
    assert result.real_provider_call_count == 0
    assert result.provider_runtime_evidence_content_hash.startswith("sha256:")
    assert result.semantic_evidence_hash == EXPECTED_SCRIPTED_SEMANTIC_EVIDENCE_HASH
    assert result.qualification_boundary == "SCRIPTED_PROTOCOL_ONLY"
    campaign = quality.require_campaign(campaign_id, principal=operator)
    assert campaign["lifecycle"] == "WAITING_HUMAN_EVIDENCE"
    assert campaign["qualification_status"] == "NOT_PROVEN"
    assert campaign["human_evidence_status"] == "WAITING_HUMAN_EVIDENCE"
    assert len(campaign["subjects"]) == 9
    assert len(campaign["evidence"]) == 3
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_external_effect_dispatch AS dispatch
            JOIN authority_external_effect AS effect
              ON effect.external_effect_id=dispatch.external_effect_id
            WHERE effect.project_id=%s AND effect.effect_type='model.invoke'
            """,
            [project_id],
        )
        model_provider_dispatch_count = int(uow.cursor.fetchone()[0])
        uow.cursor.execute(
            """
            SELECT chapter_start,chapter_end,state,accepted_through_chapter
            FROM authority_chapter_group_production
            WHERE book_run_id=%s
            ORDER BY chapter_start
            """,
            [book.book_run_id],
        )
        groups = uow.cursor.fetchall()
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_book_chapter_request
            WHERE book_run_id=%s AND chapter_number=9
            """,
            [book.book_run_id],
        )
        chapter_nine = int(uow.cursor.fetchone()[0])
        uow.cursor.execute(
            """
            SELECT COUNT(*), COUNT(*) FILTER (WHERE status='SUCCEEDED')
            FROM authority_reader_outcome_projection
            WHERE book_run_id=%s
            """,
            [book.book_run_id],
        )
        reader_counts = tuple(int(value) for value in uow.cursor.fetchone())
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_longform_recap_projection
            WHERE book_run_id=%s AND status='SUCCEEDED'
            """,
            [book.book_run_id],
        )
        recap_count = int(uow.cursor.fetchone()[0])
        uow.cursor.execute(
            """
            SELECT COUNT(*), array_agg(chapter_start ORDER BY chapter_start),
                   array_agg(chapter_end ORDER BY chapter_start)
            FROM authority_narrative_realization
            WHERE project_id=%s AND book_id=%s
            """,
            [project_id, book_id],
        )
        realization = uow.cursor.fetchone()
        uow.cursor.execute(
            """
            SELECT reviewer_id,pack_id,pair_count,status
            FROM human_preference_evaluation_pack
            WHERE campaign_id=%s
            ORDER BY reviewer_id
            """,
            [campaign_id],
        )
        persisted_packs = uow.cursor.fetchall()
        uow.cursor.execute(
            """
            SELECT version.content, evidence.provider_lineage
            FROM authority_quality_qualification_evidence AS evidence
            JOIN authority_asset_version AS version
              ON version.asset_version_id=evidence.evidence_asset_version_id
            WHERE evidence.campaign_id=%s
              AND evidence.evidence_type='ACCEPTED_LONGITUDINAL_QUALITY'
            """,
            [campaign_id],
        )
        persisted_longitudinal = uow.cursor.fetchone()
    assert result.provider_dispatch_count == model_provider_dispatch_count
    assert [tuple(row) for row in groups] == [
        (1, 4, "COMPLETED", 4),
        (5, 8, "COMPLETED", 8),
    ]
    assert chapter_nine == 0
    assert reader_counts == (8, 8)
    assert recap_count == 2
    assert int(realization[0]) == 2
    assert list(realization[1]) == [1, 5]
    assert list(realization[2]) == [4, 8]
    assert [tuple(row[2:]) for row in persisted_packs] == [
        (9, "EXPORTED"),
        (9, "EXPORTED"),
    ]
    assert persisted_longitudinal is not None
    assert (
        persisted_longitudinal[0]["semantic_evidence_hash"]
        == result.semantic_evidence_hash
    )
    assert persisted_longitudinal[1]["mode"] == "scripted"
    assert persisted_longitudinal[1]["routes"] == profile.provider_routes["scripted"]
    for reviewer_id, pack_id, _pair_count, _status in persisted_packs:
        public = quality.reader_calibration.reviewer_pack(
            pack_id=str(pack_id),
            reviewer_id=str(reviewer_id),
            principal=operator,
        )
        rendered = json.dumps(public, ensure_ascii=False).lower()
        public_keys = _json_keys(public)
        assert len(public["pairs"]) == 9
        assert "cannot_judge" in rendered
        for forbidden_key in (
            "canonical",
            "baseline",
            "provider",
            "model",
            "prompt",
            "judge",
            "system_score",
            "asset_version",
            "private_mapping",
        ):
            assert forbidden_key not in public_keys
        assert "bounded-quality-campaign-secret-v1" not in rendered
