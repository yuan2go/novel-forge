from __future__ import annotations

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.chapter_authority.execution_gateway import (
    _provider_effective_context_policy,
)
from novel_forge.modules.context_builder.domain import (
    ContextCandidate,
    build_authority_context_bundle,
)


def test_provider_preflight_compiles_all_five_context_policy_inputs() -> None:
    bundle = build_authority_context_bundle(
        project_id="project-a",
        book_id="book-a",
        stage="draft",
        created_by_operation_id="operation-a",
        context_profile_version="draft-profile-v2",
        candidates=(
            ContextCandidate(
                asset_version_id="plan-v1",
                asset_type="chapter_plan",
                physical_asset_type="chapter_plan",
                project_id="project-a",
                book_id="book-a",
                estimated_tokens=40,
                content_digest="sha256:" + "a" * 64,
                safe_summary="governed plan",
                context_class="PROTECTED",
                provenance={"authority": "PlanningAuthority"},
            ),
        ),
        token_budget=80,
        required_asset_types=("chapter_plan",),
    )
    receipt = _provider_effective_context_policy(
        context_selection=[
            {
                "artifact_type": "context_bundle",
                "content": bundle,
            }
        ],
        context_policy_payload={
            "policy_id": "pack-context",
            "allowed_asset_types": ["context_bundle"],
            "forbidden_asset_types": ["raw_source"],
            "max_tokens": 80,
        },
        context_policy_hash="sha256:" + "b" * 64,
        context_policy_ref="pack:context-policy:v1",
        route_identity="draft:openai:gpt-test:release:snapshot",
        route_allowed_physical_types=("context_bundle",),
    )

    assert len(receipt["input_policies"]) == 5
    assert {item["identity"]["version"] for item in receipt["input_policies"]} == {
        "context-profile-v1",
        "production-stage-profile-v1",
        "caller-context-limit-v1",
        "capability-pack-context-policy-v1",
        "provider-route-context-capability-v1",
    }
    assert receipt["conflict_decision"] == "PASS"


def test_provider_route_rejects_selected_representation_it_does_not_support() -> None:
    bundle = build_authority_context_bundle(
        project_id="project-a",
        book_id="book-a",
        stage="draft",
        created_by_operation_id="operation-a",
        context_profile_version="draft-profile-v2",
        candidates=(
            ContextCandidate(
                asset_version_id="plan-v1",
                asset_type="chapter_plan",
                physical_asset_type="chapter_plan",
                project_id="project-a",
                book_id="book-a",
                estimated_tokens=40,
                content_digest="sha256:" + "a" * 64,
                safe_summary="governed plan",
                context_class="PROTECTED",
                provenance={"authority": "PlanningAuthority"},
            ),
        ),
        token_budget=80,
        required_asset_types=("chapter_plan",),
    )

    with pytest.raises(KernelError, match="Provider route does not admit"):
        _provider_effective_context_policy(
            context_selection=[
                {"artifact_type": "context_bundle", "content": bundle}
            ],
            context_policy_payload={
                "policy_id": "pack-context",
                "allowed_asset_types": ["context_bundle", "chapter_memo"],
                "forbidden_asset_types": [],
                "max_tokens": 80,
            },
            context_policy_hash="sha256:" + "b" * 64,
            context_policy_ref="pack:context-policy:v1",
            route_identity="retrieval:openai:gpt-test:release:snapshot",
            route_allowed_physical_types=("chapter_memo",),
        )
