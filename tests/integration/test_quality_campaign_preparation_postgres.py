from __future__ import annotations

from pathlib import Path
import tempfile
from uuid import uuid4

from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.runtime_proof import (
    BoundedQualityCampaignPreparer,
    load_quality_book_contract,
    load_quality_campaign_profile,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated


ROOT = Path(__file__).resolve().parents[2]
RELEASE_SHA = "9" * 40


def test_scripted_quality_preparation_reaches_one_unstarted_eight_chapter_book() -> (
    None
):
    ensure_migrated()
    profile = load_quality_campaign_profile(
        ROOT / "config/proof_campaigns/quality_qualification_v1.json",
        repository_root=ROOT,
    )
    book_contract = load_quality_book_contract(
        ROOT / "config/proof_campaigns/quality_qualification_book_v1.json",
        campaign_profile=profile,
    )
    with tempfile.TemporaryDirectory(prefix="quality-preparation-") as object_root:
        settings = IndustrialSettings(
            root=ROOT,
            environment="test",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
        campaign_id = f"scripted-quality-preparation:{uuid4().hex}"
        preparer = BoundedQualityCampaignPreparer(
            database_url=DATABASE_URL,
            repository_root=ROOT,
            settings=settings,
            runtime_env={
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": object_root,
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_BACKEND": "local",
            },
            profile=profile,
            book_contract=book_contract,
            campaign_id=campaign_id,
            exact_release_sha=RELEASE_SHA,
            mode="scripted",
        )
        result = preparer.prepare()
        replayed = preparer.prepare()

    assert replayed.to_dict() == result.to_dict()
    assert set(result.capability_pack_manifest) == {
        "planning",
        "chapter",
        "reader_proxy",
        "narrative_evaluation",
    }
    assert len(result.planning_lineage["arc_plan_asset_version_ids"]) == 1
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT target_chapter_count,accepted_through_chapter,
                   light_recap_cadence,formal_recap_cadence,input_mode
            FROM authority_book_production
            WHERE book_run_id=%s
            """,
            [result.book_run_id],
        )
        book = uow.cursor.fetchone()
        uow.cursor.execute(
            """
            SELECT COUNT(*),COUNT(DISTINCT foundation_role),MIN(run.lifecycle)
            FROM authority_book_foundation_binding AS binding
            JOIN authority_story_formation_run AS run
              ON run.formation_run_id=binding.formation_run_id
            WHERE binding.project_id=%s AND binding.book_id=%s
              AND binding.freshness='CURRENT'
            """,
            [result.project_id, result.book_id],
        )
        foundation = uow.cursor.fetchone()
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_narrative_design_qualification
            WHERE project_id=%s AND evaluator_execution_class='OPERATOR_REVIEW'
            """,
            [result.project_id],
        )
        operator_reviews = int(uow.cursor.fetchone()[0])
    assert book == (8, 0, 4, 8, "RESOLVED_AUTHORITY_INPUT")
    assert foundation == (6, 6, "READY")
    assert operator_reviews == 7
