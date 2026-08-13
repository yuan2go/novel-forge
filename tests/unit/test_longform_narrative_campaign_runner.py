from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

from novel_forge.modules.chapter_outcome.domain import (
    build_chapter_outcome,
    reduce_story_state,
)
from novel_forge.modules.book_authority.input_resolver import (
    BookProductionInputResolver,
    ResolveBookProductionInputCommand,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state import project_entity_state


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


@pytest.mark.parametrize("target", (1, 2, 5, 30, 100, 300))
def test_campaign_accepts_bounded_cumulative_targets(target: int) -> None:
    campaign = _load_script()

    assert campaign._validate_target(target) == target


@pytest.mark.parametrize("target", (0, 31, 299, 301))
def test_campaign_rejects_non_checkpoint_targets(target: int) -> None:
    campaign = _load_script()

    with pytest.raises(ValueError, match="target chapter"):
        campaign._validate_target(target)


def test_language_contract_failure_is_distinct_from_authority_acceptance() -> None:
    campaign = _load_script()

    assert (
        campaign._classify_failure(
            RuntimeError("PROOF_LANGUAGE_CONTRACT_FAILED: accepted English prose")
        )
        == "PROOF_CONTRACT_FAILURE"
    )


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


def test_resume_cannot_turn_authority_accepted_wrong_language_into_proof_pass() -> None:
    campaign = _load_script()
    checkpoint = {
        "contract_identity": "sha256:" + "a" * 64,
        "release": {"commit_sha": "b" * 40},
        "accepted_through_chapter": 1,
        "chapter_exports": [
            {
                "chapter": 1,
                "authority_acceptance_status": "ACCEPTED",
                "proof_acceptance_status": "FAILED",
            }
        ],
    }

    with pytest.raises(RuntimeError, match="Proof-invalid accepted Chapter"):
        campaign._validate_resume_checkpoint(
            checkpoint,
            contract_identity="sha256:" + "a" * 64,
            commit_sha="b" * 40,
            target_chapter=2,
        )


def test_frozen_provider_policy_rejects_cli_drift_and_overrides_legacy_planning() -> None:
    campaign = _load_script()
    provider = {
        "provider": "codex-cli",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
        "quality_context_token_budget": 28_000,
        "silent_fallback": False,
    }

    campaign._validate_frozen_provider_policy(
        provider,
        model="gpt-5.6-sol",
        reasoning_effort="high",
        quality_context_token_budget=28_000,
    )
    env = campaign._apply_frozen_provider_policy(
        {
            "NOVEL_FORGE_MODEL_PROVIDER": "codex-cli",
            "NOVEL_FORGE_PLANNING_REASONING_EFFORT": "xhigh",
        },
        provider,
    )
    assert env["NOVEL_FORGE_PLANNING_REASONING_EFFORT"] == "high"
    assert env["NOVEL_FORGE_REASONING_EFFORT"] == "high"

    with pytest.raises(RuntimeError, match="model differs"):
        campaign._validate_frozen_provider_policy(
            provider,
            model="another-model",
            reasoning_effort="high",
            quality_context_token_budget=28_000,
        )


def test_process_failure_is_persisted_before_campaign_checkpoint_exists(
    tmp_path: Path,
) -> None:
    campaign = _load_script()

    path = campaign._record_process_failure(
        tmp_path,
        RuntimeError("frozen Provider configuration drift"),
        category="PROOF_HARNESS_DEFECT",
        context={"phase": "INITIALISATION"},
    )

    payload = __import__("json").loads(path.read_text(encoding="utf-8"))
    assert payload["failures"][0]["category"] == "PROOF_HARNESS_DEFECT"
    assert payload["failures"][0]["context"] == {"phase": "INITIALISATION"}


def test_campaign_counts_embedded_narrative_context_manifests(monkeypatch) -> None:
    campaign = _load_script()
    observed_sql: list[str] = []

    def query_rows(_database_url: str, sql: str, _params):
        observed_sql.append(sql)
        if "authority_book_chapter_request" in sql:
            return [{"chapter_number": 1, "accepted": 1}]
        if (
            "asset_type='context_bundle'" in sql
            and "content->'context_manifest'->>'contract_version'" in sql
        ):
            return [{"count": 1}]
        return [{"count": 0}]

    monkeypatch.setattr(campaign, "_query_rows", query_rows)

    measurements = campaign._collect_measurements(
        "postgresql://authority",
        project_id="project-1",
        book_run_id="book-run-1",
    )

    assert measurements["context_manifests"] == 1
    assert measurements["duplicate_logical_chapters"] == 0
    assert any("asset_type='context_bundle'" in sql for sql in observed_sql)


def test_frozen_initial_narrative_state_supports_first_chapter_resource_delta() -> None:
    campaign = _load_script()
    root = Path(__file__).resolve().parents[2]
    contract = json.loads(
        (root / "config/proof_campaigns/longform_narrative_v1.json").read_text(
            encoding="utf-8"
        )
    )
    story_state, canon = campaign._campaign_initial_narrative_snapshots(
        project_id="project-1",
        book_id="book-1",
        campaign_contract=contract,
    )
    outcome = build_chapter_outcome(
        project_id="project-1",
        book_id="book-1",
        chapter_number=1,
        chapter_plan_version_id="plan-v1",
        parent_group_version_id="group-v1",
        accepted_draft_version_id="draft-v1",
        final_release_gate_version_id="release-v1",
        quality_aggregate_version_id="quality-v1",
        canon_patch_asset_version_id="canon-patch-v1",
        canon_patch={
            "gate": "PASSED",
            "conflicts": [],
            "state_changes": {
                "resource_state": [
                    {
                        "entity_id": "resource:dry-seals",
                        "resource_id": "resource:dry-seals",
                        "balance_before": 3,
                        "delta": -1,
                        "balance_after": 2,
                        "effective_from_chapter": 1,
                    }
                ]
            },
        },
        cost_receipt_refs=("cost-v1",),
        created_by_operation_id="operation-v1",
        trace_id="trace-v1",
    )

    reduced = reduce_story_state(
        previous=story_state,
        chapter_outcome=outcome,
        chapter_outcome_asset_version_id="outcome-v1",
        previous_story_state_asset_version_id="initial-story-state-v1",
    )

    resource = project_entity_state(
        reduced,
        "resource_state",
        "entity_id=resource:dry-seals|resource_id=resource:dry-seals",
    )
    assert resource["state"]["balance"] == 2
    assert story_state["accepted_through_chapter"] == 0
    assert canon["accepted_through_chapter"] == 0
    assert canon["story_state_hash"] == story_state["state_hash"]
    assert story_state["initial_state_boundary"] == "BOOK_PRODUCTION_INPUT_SNAPSHOT"


def test_resource_baseline_failure_is_proof_harness_defect() -> None:
    campaign = _load_script()

    assert (
        campaign._classify_failure(
            RuntimeError(
                "NARRATIVE_RESOURCE_STATE_MISSING: resource delta cannot apply "
                "before an accepted balance exists"
            )
        )
        == "PROOF_HARNESS_DEFECT"
    )


def test_book_input_requires_complete_integrity_bound_initial_state_pair() -> None:
    campaign = _load_script()
    root = Path(__file__).resolve().parents[2]
    contract = json.loads(
        (root / "config/proof_campaigns/longform_narrative_v1.json").read_text(
            encoding="utf-8"
        )
    )
    story_state, canon = campaign._campaign_initial_narrative_snapshots(
        project_id="project-1",
        book_id="book-1",
        campaign_contract=contract,
    )
    BookProductionInputResolver._validate_initial_narrative_state_pair(
        project_id="project-1",
        book_id="book-1",
        initial_roles={
            "initial_story_state_version": {"content": story_state},
            "initial_canon_snapshot_version": {"content": canon},
        },
    )

    tampered = {**story_state, "state_version": 99}
    with pytest.raises(KernelError, match="integrity-bound"):
        BookProductionInputResolver._validate_initial_narrative_state_pair(
            project_id="project-1",
            book_id="book-1",
            initial_roles={
                "initial_story_state_version": {"content": tampered},
                "initial_canon_snapshot_version": {"content": canon},
            },
        )

    with pytest.raises(ValueError, match="role overrides"):
        ResolveBookProductionInputCommand(
            project_id="project-1",
            workspace_id="workspace-1",
            book_id="book-1",
            production_profile="production-v1",
            expected_book_version=1,
            actor_id="operator-1",
            idempotency_key="resolve-1",
            trace_id="trace-1",
            correlation_id="correlation-1",
            role_asset_version_overrides=(
                ("initial_story_state_version", "story-state-v1"),
            ),
        )
