from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_retired_agent_and_provider_compatibility_adapters_are_absent() -> None:
    for relative in (
        "src/novel_forge/modules/agent_runtime/bootstrap.py",
        "src/novel_forge/modules/provider_control/compatibility.py",
    ):
        assert not (ROOT / relative).exists(), relative

    combined = "\n".join(
        (
            _read("src/novel_forge/modules/provider_control/__init__.py"),
            _read("src/novel_forge/modules/chapter_authority/__init__.py"),
        )
    )
    for retired_symbol in (
        "LegacyAgentProfileBootstrapAdapter",
        "LegacyProviderCompatibilityAdapter",
        "ChapterModelExternalEffectAdapter",
        "ChapterModelRoute",
    ):
        assert retired_symbol not in combined


def test_chapter_model_effects_only_expose_the_shared_gateway_port() -> None:
    effects = _read("src/novel_forge/modules/chapter_authority/model_effects.py")
    assert "class ExternalEffectChapterModelPort" in effects
    assert "class ChapterModelExternalEffectAdapter" not in effects
    assert "LegacyChapterModelAdapter" not in effects
    assert "legacy_independent_execution" not in effects


def test_authority_api_has_one_production_composition_profile() -> None:
    combined = "\n".join(
        (
            _read("src/novel_forge/api/authority_app.py"),
            _read("src/novel_forge/infrastructure/settings.py"),
            _read("compose.yml"),
        )
    )
    for retired_marker in (
        "TrackBMinimalAuthorityServices",
        "_create_track_b_minimal_app",
        "track-b-minimal",
        "NOVEL_FORGE_AUTHORITY_RUNTIME_PROFILE",
    ):
        assert retired_marker not in combined


def test_obsolete_quality_and_unbounded_campaign_surfaces_are_absent() -> None:
    retired_paths = (
        "src/novel_forge/modules/runtime_proof/__init__.py",
        "src/novel_forge/modules/runtime_proof/quality_campaign.py",
        "src/novel_forge/modules/runtime_proof/quality_campaign_postgres.py",
        "src/novel_forge/modules/runtime_proof/quality_preparation.py",
        "src/novel_forge/modules/runtime_proof/short_longform.py",
        "src/novel_forge/evaluation/quality.py",
        "src/novel_forge/modules/runtime_proof/longform_campaign.py",
        "scripts/run_longform_narrative_campaign.py",
        "scripts/run_long_chain_to_completion.py",
        "scripts/run_bounded_quality_qualification.py",
        "scripts/run_short_longform_runtime_proof.py",
        "scripts/run_short_longform_runtime_proof_orchestrator.py",
        "config/proof_campaigns/quality_qualification_book_v1.json",
        "config/proof_campaigns/quality_qualification_v1.json",
        "config/proof_campaigns/longform_narrative_v1.json",
        "config/proof_campaigns/longform_narrative_v2.json",
        "tests/unit/test_longform_narrative_campaign.py",
        "tests/unit/test_longform_narrative_campaign_runner.py",
        "tests/integration/test_bounded_quality_campaign_postgres.py",
        "tests/integration/test_quality_campaign_preparation_postgres.py",
        "tests/unit/test_bounded_quality_campaign.py",
        "tests/unit/test_bounded_quality_campaign_cli.py",
        "tests/unit/test_quality_book_contract.py",
        "tests/unit/test_short_longform_proof_evaluator.py",
        "tests/unit/test_short_longform_runtime_proof.py",
        "web/admin/app/quality-eval-v2/page.tsx",
        "web/admin/app/long-chain-proof/page.tsx",
    )
    for relative in retired_paths:
        assert not (ROOT / relative).exists(), relative
    legacy_generated = ROOT / "generated/longchain-webnovel"
    assert not legacy_generated.exists() or not any(
        path.is_file() for path in legacy_generated.rglob("*")
    )

    current_surfaces = "\n".join(
        (
            _read("src/novel_forge/api/models.py"),
            _read("web/admin/app/shared/navigation.tsx"),
            _read(
                "web/admin/app/features/content-intelligence/"
                "ContentIntelligencePages.tsx"
            ),
        )
    )
    for retired_marker in (
        "LongformCampaignContract",
        "LongChainProofRunRequest",
        "ProviderQualityJudgeRequest",
        "QualitySuiteRunRequest",
        "/quality-eval-v2",
        "/long-chain-proof",
        "deterministic_50",
        "mock_100",
        "state_only_300",
    ):
        assert retired_marker not in current_surfaces

    current_quality_authority = "\n".join(
        (
            _read("src/novel_forge/modules/content_authority/codecs.py"),
            _read("src/novel_forge/modules/content_authority/handlers.py"),
        )
    )
    for retired_operation in (
        "quality.golden_sample.create",
        "quality.human_decision.record",
        "quality.calibration.run",
        "quality.calibration.profile.promote",
        "quality.calibration.profile.revoke",
    ):
        assert retired_operation not in current_quality_authority
