from __future__ import annotations

import pytest

from novel_forge.modules.context_builder.domain import (
    ContextCandidate,
    build_authority_context_bundle,
    replay_context_bundle,
    resolve_context_profile,
    select_context_candidates,
)
from novel_forge.modules.context_builder.governance import (
    ContextBudgetLimits,
    ContextPolicySnapshot,
    PolicyIdentity,
    compile_effective_context_policy,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def _policy(
    name: str,
    *,
    allowed: tuple[str, ...],
    denied: tuple[str, ...] = (),
    required: tuple[str, ...] = (),
    total: int = 100,
    sections: dict[str, int] | None = None,
    buckets: dict[str, int] | None = None,
    classes: dict[str, int] | None = None,
) -> ContextPolicySnapshot:
    return ContextPolicySnapshot(
        identity=PolicyIdentity(
            policy_id=name,
            version="context-policy-v1",
            content_hash=HASH_A if name == "a" else HASH_B,
            snapshot_ref=f"snapshot:{name}",
        ),
        allowed_logical_kinds=allowed,
        denied_logical_kinds=denied,
        required_logical_kinds=required,
        limits=ContextBudgetLimits(
            total=total,
            sections=sections or {},
            buckets=buckets or {},
            classes=classes or {},
            required_reservation=0,
        ),
    )


def _candidate(identity: str, kind: str, **changes: object) -> ContextCandidate:
    values: dict[str, object] = {
        "asset_version_id": identity,
        "asset_type": kind,
        "physical_asset_type": kind,
        "project_id": "project-a",
        "estimated_tokens": 40,
        "content_digest": "sha256:" + identity.replace("-", "")[:8].ljust(64, "0"),
        "safe_summary": f"Safe material for {identity}",
        "provenance": {
            "authority_asset_version_id": identity,
            "source_content_hash": "sha256:" + "c" * 64,
        },
        "section": "NARRATIVE",
        "bucket": kind,
    }
    values.update(changes)
    return ContextCandidate(**values)


def test_effective_policy_intersects_allowlists_uses_strictest_limits() -> None:
    result = compile_effective_context_policy(
        (
            _policy(
                "a",
                allowed=("chapter_plan", "canon_snapshot", "knowledge_pack"),
                total=100,
                sections={"NARRATIVE": 80},
            ),
            _policy(
                "b",
                allowed=("chapter_plan", "canon_snapshot"),
                total=90,
                sections={"NARRATIVE": 70},
            ),
        )
    )

    assert result.effective_policy.allowed_logical_kinds == (
        "canon_snapshot",
        "chapter_plan",
    )
    assert result.effective_policy.limits.total == 90
    assert result.effective_policy.limits.sections == {"NARRATIVE": 70}
    assert result.receipt["compiler_version"] == "effective-context-policy-compiler-v1"


def test_logical_context_kind_and_physical_asset_type_are_separate_namespaces() -> None:
    logical = _policy("a", allowed=("canon_snapshot",))
    physical = ContextPolicySnapshot(
        identity=PolicyIdentity(
            policy_id="physical",
            version="provider-context-route-v1",
            content_hash=HASH_B,
            snapshot_ref="pack:physical",
        ),
        allowed_physical_types=("context_bundle",),
        limits=ContextBudgetLimits(total=80),
    )

    result = compile_effective_context_policy((logical, physical)).effective_policy

    assert result.allowed_logical_kinds == ("canon_snapshot",)
    assert result.allowed_physical_types == ("context_bundle",)


def test_effective_policy_deny_wins_and_required_conflict_fails_closed() -> None:
    with pytest.raises(ValueError, match="CONTEXT_REQUIRED_SOURCE_DENIED"):
        compile_effective_context_policy(
            (
                _policy(
                    "a",
                    allowed=("chapter_plan", "canon_snapshot"),
                    required=("canon_snapshot",),
                ),
                _policy(
                    "b",
                    allowed=("chapter_plan", "canon_snapshot"),
                    denied=("canon_snapshot",),
                ),
            )
        )


def test_unknown_policy_version_fails_closed() -> None:
    invalid = _policy("a", allowed=("chapter_plan",))
    invalid = ContextPolicySnapshot(
        identity=PolicyIdentity(
            policy_id=invalid.identity.policy_id,
            version="future-policy-v9",
            content_hash=invalid.identity.content_hash,
            snapshot_ref=invalid.identity.snapshot_ref,
        ),
        allowed_logical_kinds=invalid.allowed_logical_kinds,
        limits=invalid.limits,
    )
    with pytest.raises(ValueError, match="CONTEXT_POLICY_UNRESOLVED"):
        compile_effective_context_policy((invalid,))


def test_eligibility_dedup_and_hierarchical_budget_are_pre_rank() -> None:
    policy = compile_effective_context_policy(
        (
            _policy(
                "a",
                allowed=("chapter_plan", "canon_snapshot", "knowledge_pack"),
                required=("chapter_plan",),
                total=100,
                sections={"NARRATIVE": 100},
                buckets={"chapter_plan": 50, "knowledge_pack": 45},
                classes={"PROTECTED": 50, "RETRIEVABLE": 50},
            ),
        )
    ).effective_policy
    selection = select_context_candidates(
        project_id="project-a",
        profile=resolve_context_profile("draft"),
        candidates=(
            _candidate(
                "plan-v1",
                "chapter_plan",
                context_class="PROTECTED",
                estimated_tokens=50,
                logical_narrative_identity="chapter-plan:1",
            ),
            _candidate(
                "knowledge-v1",
                "knowledge_pack",
                relevance_score=0.8,
                semantic_representation_identity="knowledge:seal",
            ),
            _candidate(
                "knowledge-v2",
                "knowledge_pack",
                relevance_score=0.9,
                semantic_representation_identity="knowledge:seal",
            ),
            _candidate(
                "stale-v1",
                "knowledge_pack",
                authority_freshness="STALE",
                relevance_score=1.0,
            ),
            _candidate(
                "debug-v1",
                "provider_debug_payload",
                relevance_score=1.0,
            ),
        ),
        token_budget=100,
        effective_policy=policy,
    )

    assert [item.asset_version_id for item in selection.selected] == [
        "plan-v1",
        "knowledge-v2",
    ]
    decisions = {item["asset_version_id"]: item for item in selection.decisions}
    assert decisions["knowledge-v1"]["reason"] == "DUPLICATE_REPRESENTATION"
    assert decisions["knowledge-v1"]["winner_asset_version_id"] == "knowledge-v2"
    assert decisions["stale-v1"]["reason"] == "STALE_REPRESENTATION"
    assert decisions["debug-v1"]["reason"] == "DIAGNOSTIC_CONTEXT_FORBIDDEN"
    assert selection.token_accounting["tokens_by_class"] == {
        "PROTECTED": 50,
        "RETRIEVABLE": 40,
    }


def test_structured_truncation_preserves_elements_and_provenance() -> None:
    policy = compile_effective_context_policy(
        (
            _policy(
                "a",
                allowed=("chapter_plan", "knowledge_pack"),
                required=("chapter_plan",),
                total=75,
                sections={"NARRATIVE": 75},
                buckets={"chapter_plan": 50, "knowledge_pack": 25},
                classes={"PROTECTED": 50, "COMPRESSIBLE": 25},
            ),
        )
    ).effective_policy
    selection = select_context_candidates(
        project_id="project-a",
        profile=resolve_context_profile("draft"),
        candidates=(
            _candidate(
                "plan-v1",
                "chapter_plan",
                context_class="PROTECTED",
                estimated_tokens=50,
            ),
            _candidate(
                "knowledge-v1",
                "knowledge_pack",
                context_class="COMPRESSIBLE",
                estimated_tokens=40,
                safe_summary="",
                structured_facts=(
                    {"fact_id": "fact:1", "value": "one"},
                    {"fact_id": "fact:2", "value": "two"},
                    {"fact_id": "fact:3", "value": "three"},
                ),
                truncation_strategy="structured_elements-v1",
            ),
        ),
        token_budget=75,
        effective_policy=policy,
    )

    assert [item.asset_version_id for item in selection.selected] == [
        "plan-v1",
        "knowledge-v1",
    ]
    assert selection.selected[1].estimated_tokens <= 25
    assert 0 < len(selection.selected[1].structured_facts) < 3
    receipt = selection.truncations[0]
    assert receipt["strategy"] == "structured_elements-v1"
    assert receipt["before_hash"].startswith("sha256:")
    assert receipt["after_hash"].startswith("sha256:")
    assert receipt["removed_element_count"] > 0


def test_new_manifest_freezes_compiler_and_complete_decisions() -> None:
    bundle = build_authority_context_bundle(
        project_id="project-a",
        book_id="book-a",
        stage="draft",
        created_by_operation_id="operation-a",
        context_profile_version="draft-profile-v2",
        candidates=(
            _candidate(
                "plan-v1",
                "chapter_plan",
                context_class="PROTECTED",
                estimated_tokens=40,
            ),
        ),
        token_budget=80,
        required_asset_types=("chapter_plan",),
        authority_state_boundary={"accepted_through_chapter": 0},
    )

    manifest = bundle["context_manifest"]
    assert bundle["context_contract_version"] == "authority-context-bundle-v8"
    assert manifest["contract_version"] == "narrative-context-manifest-v4"
    assert manifest["effective_policy"]["compiler_version"] == (
        "effective-context-policy-compiler-v1"
    )
    assert manifest["metrics"]["candidate_count"] == 1
    assert manifest["metrics"]["accepted_count"] == 1
    assert manifest["token_accounting_contract"]["precision"] == "ESTIMATE_ONLY"
    assert manifest["replay"]["algorithm"] == "authority-context-selection-v3-governed"


def test_historical_v7_replay_uses_frozen_semantics_without_current_compiler() -> None:
    manifest = {
        "type": "NarrativeContextManifest",
        "contract_version": "narrative-context-manifest-v3",
        "selected_inputs": [],
        "replay": {
            "algorithm": "authority-context-selection-v2-four-class",
            "input_digest": "sha256:" + "1" * 64,
            "output_context_digest": "sha256:" + "2" * 64,
        },
    }
    import hashlib
    import json

    manifest["context_fingerprint"] = "sha256:" + hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    frozen = {
        "context_contract_version": "authority-context-bundle-v7",
        "actual_context_digest": "sha256:" + "2" * 64,
        "context_manifest": manifest,
    }

    replay = replay_context_bundle(frozen)

    assert replay["status"] == "MATCH"
    assert replay["semantics"] == "FROZEN_V7"
    assert replay["current_policy_compiler_invoked"] is False
