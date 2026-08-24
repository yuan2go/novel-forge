import pytest

from novel_forge.modules.artifact_lineage import (
    ArtifactLineageEdge,
    InvalidationPolicy,
    SemanticDiff,
    lineage_policy_for,
    semantic_dimensions_for,
)


def test_lineage_identity_is_stable_and_accepted_history_is_immune() -> None:
    edge = ArtifactLineageEdge(
        project_id="project-1",
        book_id="book-1",
        upstream_asset_version_id="plan-v1",
        downstream_asset_version_id="context-v1",
        relationship_type="CONSUMES",
        semantic_dimensions=semantic_dimensions_for(("chapter_plan", "context_bundle")),
        invalidation_policy=lineage_policy_for("context_bundle"),
        context_fingerprint="sha256:" + "a" * 64,
        created_by_operation_id="operation-1",
    )
    replay = ArtifactLineageEdge(
        **{
            "project_id": edge.project_id,
            "book_id": edge.book_id,
            "upstream_asset_version_id": edge.upstream_asset_version_id,
            "downstream_asset_version_id": edge.downstream_asset_version_id,
            "relationship_type": edge.relationship_type,
            "semantic_dimensions": edge.semantic_dimensions,
            "invalidation_policy": edge.invalidation_policy,
            "context_fingerprint": edge.context_fingerprint,
            "created_by_operation_id": edge.created_by_operation_id,
        }
    )

    assert edge.lineage_edge_id == replay.lineage_edge_id
    assert edge.invalidation_policy is InvalidationPolicy.REQUALIFY
    assert (
        lineage_policy_for("accepted_chapter")
        is InvalidationPolicy.IMMUNE_ACCEPTED_HISTORY
    )
    assert (
        lineage_policy_for("reader_outcome_report")
        is InvalidationPolicy.IMMUNE_ACCEPTED_HISTORY
    )
    assert (
        lineage_policy_for("reader_state_transition")
        is InvalidationPolicy.IMMUNE_ACCEPTED_HISTORY
    )
    assert (
        lineage_policy_for("longform_recap")
        is InvalidationPolicy.IMMUNE_ACCEPTED_HISTORY
    )
    assert (
        lineage_policy_for("replan_request")
        is InvalidationPolicy.IMMUNE_ACCEPTED_HISTORY
    )


def test_semantic_diff_requires_explicit_dimensions_and_evidence() -> None:
    with pytest.raises(ValueError, match="semantic diff"):
        SemanticDiff(
            source_asset_version_id="plan-v1",
            dimensions=(),
            summary="changed",
            evidence={},
        )
