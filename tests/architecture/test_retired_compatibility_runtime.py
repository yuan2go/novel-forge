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
