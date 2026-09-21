from __future__ import annotations

from typing import Any, Sequence


def semantic_impact_projection(
    *,
    target_asset_version_id: str,
    proposed_asset_version_id: str,
    changes: Sequence[dict[str, Any]],
    finding: dict[str, Any],
    exact_dependencies: Sequence[dict[str, Any]],
    accepted_sources: Sequence[dict[str, Any]],
    uncovered_ranges: Sequence[dict[str, Any]],
    confirmation_rationale: str,
) -> dict[str, Any]:
    citation_evidence = [
        citation for member in finding["members"] for citation in member["evidence"]
    ]
    confidence = min((member["confidence"] for member in finding["members"]), default=0)
    semantic = {
        "asset_version_id": target_asset_version_id,
        "proposed_asset_version_id": proposed_asset_version_id,
        "status": "NEEDS_REVIEW",
        "basis": "INFERRED_SEMANTIC_IMPACT",
        "confidence": confidence,
        "reason": confirmation_rationale,
        "prose_evidence": citation_evidence,
        "plan_positions": [
            {
                "target_asset_version_id": target_asset_version_id,
                "proposed_asset_version_id": proposed_asset_version_id,
                "json_pointer": "/"
                + item["field"].replace("~", "~0").replace("/", "~1"),
                "before": item["before"],
                "after": item["after"],
            }
            for item in changes
        ],
        "human_confirmation_required": True,
    }
    required, review = [], [semantic]
    preserve = [
        {
            "asset_version_id": source["asset_version_id"],
            "status": "PRESERVE",
            "basis": "ACCEPTED_HISTORY_READ_ONLY",
            "text_hash": source["text_hash"],
        }
        for source in accepted_sources
    ]
    for dependency in exact_dependencies:
        item = {
            **dependency,
            "basis": "EXACT_DECLARED_DEPENDENCY",
            "conditional_on_approved_activation": True,
        }
        if dependency["execution_scope"] == "EXECUTED":
            preserve.append({**item, "status": "PRESERVE"})
        elif (
            dependency["execution_scope"] == "PLANNED"
            and dependency["requires_invalidation"]
        ):
            required.append({**item, "status": "MUST_CHANGE"})
        else:
            review.append({**item, "status": "NEEDS_REVIEW"})
    unknown = [
        {
            **item,
            "status": "UNKNOWN",
            "basis": "UNPROVIDED_PROSE",
            "reason": "unread text cannot support a semantic conclusion",
        }
        for item in uncovered_ranges
    ]
    return {
        "schema_version": "plan-semantic-impact-projection.v1",
        "classification": "INFERRED_REQUIRES_AUTHORITY_APPROVAL",
        "required": required,
        "needs_review": review,
        "preserve": preserve,
        "unknown": unknown,
        "exact_dependency_closure": list(exact_dependencies),
        "semantic_candidates": [semantic],
        "hard_dependency_created": False,
        "plan_activation_performed": False,
    }


def exact_plan_dependency_closure(
    cursor: Any, *, project_id: str, book_id: str, target_asset_version_id: str
) -> list[dict[str, Any]]:
    cursor.execute(
        """WITH RECURSIVE closure(asset_version_id,path,policies) AS (
        SELECT dependent_asset_version_id, ARRAY[source_asset_version_id,dependent_asset_version_id]::TEXT[], ARRAY[invalidation_policy]::TEXT[]
        FROM asset_dependency_edge WHERE project_id=%s AND source_asset_version_id=%s AND invalidation_policy<>'NONE'
        UNION ALL
        SELECT edge.dependent_asset_version_id, closure.path || edge.dependent_asset_version_id, closure.policies || edge.invalidation_policy
        FROM closure JOIN asset_dependency_edge edge ON edge.source_asset_version_id=closure.asset_version_id AND edge.project_id=%s
        WHERE NOT edge.dependent_asset_version_id=ANY(closure.path) AND edge.invalidation_policy<>'NONE'
    ) SELECT closure.asset_version_id, binding.execution_scope, BOOL_OR('MARK_STALE'=ANY(closure.policies)), ARRAY_AGG(DISTINCT closure.path::TEXT)
      FROM closure JOIN story_plan_binding binding ON binding.asset_version_id=closure.asset_version_id AND binding.project_id=%s AND binding.book_id=%s
      GROUP BY closure.asset_version_id,binding.execution_scope ORDER BY closure.asset_version_id""",
        [project_id, target_asset_version_id, project_id, project_id, book_id],
    )
    return [
        {
            "asset_version_id": row[0],
            "execution_scope": row[1],
            "requires_invalidation": row[2],
            "dependency_paths": row[3],
        }
        for row in cursor.fetchall()
    ]
