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


def test_convergent_lineage_is_vertex_bounded_and_history_stops_its_route() -> None:
    from novel_forge.modules.artifact_lineage import _lineage_impacts

    rows = []
    prior = ["root"]
    for level in range(24):
        current = [f"{level}:a", f"{level}:b"]
        rows.extend(
            (source, target, "PROPAGATE", "context_bundle", False)
            for source in prior
            for target in current
        )
        prior = current
    rows.extend(
        [
            ("23:a", "root", "PROPAGATE", "context_bundle", False),
            ("root", "accepted", "PROPAGATE", "story_state_snapshot", True),
            ("accepted", "future-from-history", "PROPAGATE", "context_bundle", False),
            (
                "root",
                "immune-route",
                "IMMUNE_ACCEPTED_HISTORY",
                "context_bundle",
                False,
            ),
            (
                "immune-route",
                "future-from-immune",
                "PROPAGATE",
                "context_bundle",
                False,
            ),
            ("0:a", "immune-route", "PROPAGATE", "context_bundle", False),
        ]
    )
    impacts = {row[0]: row for row in _lineage_impacts("root", rows)}
    assert len(impacts) == 51
    assert impacts["23:b"][3] == 24
    assert "root" not in impacts and "future-from-history" not in impacts
    assert impacts["accepted"][4] is True
    assert impacts["immune-route"][1] == "PROPAGATE"
    assert "future-from-immune" in impacts
