from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


def _load_script():
    root = Path(__file__).resolve().parents[2]
    scripts = root / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location(
            "run_longform_narrative_campaign",
            scripts / "run_longform_narrative_campaign.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(scripts))


@pytest.mark.parametrize("target", (1, 30, 100, 300))
def test_campaign_accepts_bounded_cumulative_targets(target: int) -> None:
    campaign = _load_script()

    assert campaign._validate_target(target) == target


@pytest.mark.parametrize("target", (0, 31, 299, 301))
def test_campaign_rejects_non_checkpoint_targets(target: int) -> None:
    campaign = _load_script()

    with pytest.raises(ValueError, match="target chapter"):
        campaign._validate_target(target)


@pytest.mark.parametrize(
    ("message", "category"),
    (
        ("codex login credential unavailable", "PROVIDER_FAILURE"),
        ("context manifest omits required fact", "CONTEXT_DEFECT"),
        ("PostgreSQL connection refused", "ENVIRONMENT_BLOCKER"),
        ("chapter prose violates frozen canon", "CONTENT_CORRECTNESS_FAILURE"),
        ("quality corrective action regressed", "CONTENT_QUALITY_FAILURE"),
        ("supervisor state invariant failed", "RUNTIME_DEFECT"),
    ),
)
def test_campaign_failure_classification_is_explicit(
    message: str, category: str
) -> None:
    campaign = _load_script()

    assert campaign._classify_failure(RuntimeError(message)) == category


def test_resume_checkpoint_must_match_contract_release_and_target() -> None:
    campaign = _load_script()
    checkpoint = {
        "contract_identity": "sha256:" + "a" * 64,
        "release": {"commit_sha": "b" * 40},
        "accepted_through_chapter": 30,
    }

    campaign._validate_resume_checkpoint(
        checkpoint,
        contract_identity="sha256:" + "a" * 64,
        commit_sha="b" * 40,
        target_chapter=100,
    )

    with pytest.raises(RuntimeError, match="another Proof Contract"):
        campaign._validate_resume_checkpoint(
            checkpoint,
            contract_identity="sha256:" + "c" * 64,
            commit_sha="b" * 40,
            target_chapter=100,
        )
    with pytest.raises(RuntimeError, match="another exact HEAD"):
        campaign._validate_resume_checkpoint(
            checkpoint,
            contract_identity="sha256:" + "a" * 64,
            commit_sha="d" * 40,
            target_chapter=100,
        )
    with pytest.raises(RuntimeError, match="behind the durable cursor"):
        campaign._validate_resume_checkpoint(
            checkpoint,
            contract_identity="sha256:" + "a" * 64,
            commit_sha="b" * 40,
            target_chapter=1,
        )
