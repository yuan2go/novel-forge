from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Sequence

from novel_forge.modules.command_kernel.errors import KernelError


DISCOVERY_POLICY = {
    "version": "bounded-plan-impact.v1",
    "plan_limit": 128,
    "prose_limit": 32,
    "hypothesis_limit": 32,
    "evidence_limit": 8,
    "impact_limit": 64,
    "prose_character_limit": 100_000,
}


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _leaves(value: Any, pointer: str = "") -> list[tuple[str, str]]:
    if isinstance(value, dict):
        return [
            leaf
            for key, child in sorted(value.items())
            for leaf in _leaves(
                child, pointer + "/" + key.replace("~", "~0").replace("/", "~1")
            )
        ]
    if isinstance(value, list):
        return [
            leaf
            for index, child in enumerate(value)
            for leaf in _leaves(child, f"{pointer}/{index}")
        ]
    return [(pointer, value)] if isinstance(value, str) else []


def discover_semantic_impacts(
    *,
    target_asset_version_id: str,
    proposed_asset_version_id: str,
    changes: Sequence[dict[str, Any]],
    plans: Sequence[dict[str, Any]],
    accepted_prose: Sequence[dict[str, Any]],
    coverage: dict[str, Any],
) -> dict[str, Any]:
    terms = []
    for change in changes:
        for side in ("before", "after"):
            for pointer, value in _leaves(change[side], "/" + change["field"]):
                if 4 <= len(value.strip()) <= 256:
                    terms.append(
                        {"side": side, "json_pointer": pointer, "value": value}
                    )
    hypotheses = []
    matched_count = 0
    for plan in plans:
        if plan["asset_version_id"] in {
            target_asset_version_id,
            proposed_asset_version_id,
        }:
            continue
        matches = []
        for pointer, value in _leaves(plan["content"]):
            for term in terms:
                if term["value"] in value:
                    matches.append(
                        {
                            "source_position": term,
                            "asset_version_id": plan["asset_version_id"],
                            "content_hash": plan["content_hash"],
                            "json_pointer": pointer,
                            "quote": term["value"],
                            "value_hash": _digest(value),
                            "start": value.index(term["value"]),
                            "end": value.index(term["value"]) + len(term["value"]),
                        }
                    )
                    if len(matches) >= DISCOVERY_POLICY["evidence_limit"]:
                        break
            if len(matches) >= DISCOVERY_POLICY["evidence_limit"]:
                break
        if not matches:
            continue
        matched_count += 1
        if len(hypotheses) >= DISCOVERY_POLICY["hypothesis_limit"]:
            continue
        prose_evidence = []
        for prose in accepted_prose:
            for term in {item["source_position"]["value"] for item in matches}:
                start = prose["text"].find(term)
                if (
                    start >= 0
                    and len(prose_evidence) < DISCOVERY_POLICY["evidence_limit"]
                ):
                    prose_evidence.append(
                        {
                            **{
                                key: prose[key]
                                for key in (
                                    "acceptance_id",
                                    "asset_version_id",
                                    "content_hash",
                                    "chapter_number",
                                )
                            },
                            "start": start,
                            "end": start + len(term),
                            "quote": term,
                        }
                    )
        snapshot = {key: value for key, value in plan.items() if key != "content"}
        identity = {
            "target": target_asset_version_id,
            "proposed": proposed_asset_version_id,
            "plan": snapshot,
            "matches": matches,
        }
        hypotheses.append(
            {
                "hypothesis_id": "semantic-impact:" + _digest(identity),
                "candidate": snapshot,
                "relation": "SHARED_CHANGED_COMMITMENT",
                "relation_status": "UNVERIFIED",
                "confidence": 0.4,
                "confidence_basis": "DETERMINISTIC_LEXICAL_RETRIEVAL_NOT_CAUSAL_PROOF",
                "plan_evidence": matches,
                "accepted_prose_evidence": prose_evidence,
                "uncertainty": [
                    "shared wording may be incidental",
                    "causal direction and relevance require Authority review",
                ],
                "default_disposition": "PRESERVE_HISTORY"
                if plan["execution_scope"] == "EXECUTED"
                else "DEFER",
            }
        )
    manifest = [
        {key: value for key, value in item.items() if key not in {"content", "text"}}
        for item in (*plans, *accepted_prose)
    ]
    return {
        "schema_version": "inferred-plan-impact.v1",
        "policy": dict(DISCOVERY_POLICY),
        "source_asset_version_id": target_asset_version_id,
        "proposed_asset_version_id": proposed_asset_version_id,
        "corpus_manifest": manifest,
        "corpus_digest": _digest(manifest),
        "coverage": {
            **coverage,
            "matched_plan_count": matched_count,
            "hypotheses_omitted": max(0, matched_count - len(hypotheses)),
            "semantic_exhaustiveness": "NOT_PROVEN",
        },
        "hypotheses": hypotheses,
        "hard_dependency_created": False,
    }


def load_semantic_impact_discovery(
    cursor: Any,
    *,
    project_id: str,
    book_id: str,
    target_asset_version_id: str,
    proposed_asset_version_id: str,
    changes: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    cursor.execute(
        """SELECT binding.asset_version_id, version.content_hash,
                  binding.logical_key,binding.contract_type,binding.execution_scope,
                  binding.version,binding.freshness,version.content,
                  (SELECT active.asset_version_id FROM active_story_plan_version active
                   WHERE active.project_id=binding.project_id AND active.book_id=binding.book_id
                     AND active.logical_key=binding.logical_key)
           FROM story_plan_binding binding
           JOIN authority_asset_version version USING(asset_version_id)
           WHERE binding.project_id=%s AND binding.book_id=%s
             AND (binding.execution_scope='EXECUTED' OR EXISTS (
               SELECT 1 FROM active_story_plan_version active WHERE active.binding_id=binding.binding_id))
           ORDER BY binding.execution_scope='EXECUTED',binding.asset_version_id LIMIT %s""",
        [project_id, book_id, DISCOVERY_POLICY["plan_limit"] + 1],
    )
    plan_rows = cursor.fetchall()
    keys = (
        "asset_version_id",
        "content_hash",
        "logical_key",
        "contract_type",
        "execution_scope",
        "binding_version",
        "freshness",
        "content",
        "active_asset_version_id",
    )
    plans = [
        dict(zip(keys, row, strict=True))
        for row in plan_rows[: DISCOVERY_POLICY["plan_limit"]]
    ]
    cursor.execute(
        """SELECT accepted.acceptance_id, draft.asset_version_id,draft.content_hash,
                  accepted.chapter_number,LEFT(draft.content->>'text',%s),LENGTH(draft.content->>'text')
           FROM authority_book_chapter_acceptance accepted
           JOIN authority_book_production book USING(book_run_id)
           JOIN authority_asset_version outcome ON outcome.asset_version_id=accepted.chapter_outcome_asset_version_id
           JOIN authority_asset_version draft ON draft.asset_version_id=outcome.content->>'accepted_draft_asset_version_id'
           WHERE accepted.project_id=%s AND book.book_id=%s AND accepted.status='COMMITTED'
           ORDER BY accepted.chapter_number DESC,accepted.acceptance_id LIMIT %s""",
        [
            DISCOVERY_POLICY["prose_character_limit"],
            project_id,
            book_id,
            DISCOVERY_POLICY["prose_limit"] + 1,
        ],
    )
    prose_rows = cursor.fetchall()
    prose = [
        dict(
            zip(
                (
                    "acceptance_id",
                    "asset_version_id",
                    "content_hash",
                    "chapter_number",
                    "text",
                    "text_length",
                ),
                row,
                strict=True,
            )
        )
        for row in prose_rows[: DISCOVERY_POLICY["prose_limit"]]
        if isinstance(row[4], str)
    ]
    discovery = discover_semantic_impacts(
        target_asset_version_id=target_asset_version_id,
        proposed_asset_version_id=proposed_asset_version_id,
        changes=changes,
        plans=plans,
        accepted_prose=prose,
        coverage={
            "plan_scan_truncated": len(plan_rows) > len(plans),
            "prose_scan_truncated": len(prose_rows) > len(prose),
            "prose_order": "LATEST_ACCEPTED_FIRST",
            "plan_scan_count": len(plans),
            "prose_scan_count": len(prose),
            "prose_character_truncated_versions": [
                item["asset_version_id"]
                for item in prose
                if item["text_length"] > len(item["text"])
            ],
        },
    )
    for hypothesis in discovery["hypotheses"]:
        candidate = hypothesis["candidate"]
        closure, truncated = bounded_dependency_snapshot(
            cursor,
            project_id=project_id,
            book_id=book_id,
            source=candidate["asset_version_id"],
        )
        hypothesis["declared_dependents"] = closure
        hypothesis["dependency_scope_truncated"] = truncated
    return discovery


def bounded_dependency_snapshot(
    cursor: Any, *, project_id: str, book_id: str, source: str
) -> tuple[list[dict[str, Any]], bool]:
    visited, frontier, result = {source}, [source], []
    while frontier:
        cursor.execute(
            """SELECT DISTINCT binding.asset_version_id,version.content_hash,
                       binding.execution_scope,binding.version,binding.freshness,
                       binding.logical_key,binding.contract_type,
                       (SELECT active.asset_version_id FROM active_story_plan_version active
                        WHERE active.project_id=binding.project_id AND active.book_id=binding.book_id
                          AND active.logical_key=binding.logical_key)
               FROM asset_dependency_edge edge
               JOIN story_plan_binding binding ON binding.asset_version_id=edge.dependent_asset_version_id
               JOIN authority_asset_version version ON version.asset_version_id=binding.asset_version_id
               WHERE edge.project_id=%s AND binding.project_id=%s AND binding.book_id=%s
                 AND edge.source_asset_version_id=ANY(%s) AND edge.invalidation_policy<>'NONE'
                 AND NOT binding.asset_version_id=ANY(%s)
               ORDER BY binding.asset_version_id LIMIT %s""",
            [
                project_id,
                project_id,
                book_id,
                frontier,
                sorted(visited),
                DISCOVERY_POLICY["impact_limit"] + 1,
            ],
        )
        rows = cursor.fetchall()
        if len(result) + len(rows) > DISCOVERY_POLICY["impact_limit"]:
            return result, True
        frontier = []
        for row in rows:
            item = dict(
                zip(
                    (
                        "asset_version_id",
                        "content_hash",
                        "execution_scope",
                        "binding_version",
                        "freshness",
                        "logical_key",
                        "contract_type",
                        "active_asset_version_id",
                    ),
                    row,
                    strict=True,
                )
            )
            result.append(item)
            visited.add(item["asset_version_id"])
            if item["execution_scope"] != "EXECUTED":
                frontier.append(item["asset_version_id"])
    return result, False


def resolve_semantic_dispositions(
    discovery: dict[str, Any], dispositions: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    hypotheses = {
        item["hypothesis_id"]: item for item in discovery.get("hypotheses", [])
    }
    resolved, seen, impacted = [], set(), set()
    for disposition in dispositions:
        hypothesis_id = disposition.get("hypothesis_id")
        if hypothesis_id not in hypotheses or hypothesis_id in seen:
            raise KernelError(
                "PLAN_IMPACT_DISPOSITION_INVALID",
                "disposition must bind one frozen hypothesis exactly once",
            )
        seen.add(hypothesis_id)
        hypothesis = hypotheses[hypothesis_id]
        outcome = disposition.get("disposition")
        if (
            outcome not in {"CONFIRMED", "FALSE_POSITIVE", "DEFER"}
            or not str(disposition.get("rationale") or "").strip()
        ):
            raise KernelError(
                "PLAN_IMPACT_DISPOSITION_INVALID",
                "review requires a disposition and reason",
            )
        evidence = disposition.get("evidence") or []
        if outcome in {"CONFIRMED", "FALSE_POSITIVE"} and (
            not evidence
            or any(
                item
                not in hypothesis["plan_evidence"]
                + hypothesis["accepted_prose_evidence"]
                for item in evidence
            )
        ):
            raise KernelError(
                "PLAN_IMPACT_EVIDENCE_INVALID",
                "verified relation or false positive must cite exact frozen evidence",
            )
        if outcome == "CONFIRMED":
            if hypothesis["candidate"]["execution_scope"] not in {
                "PLANNED",
                "SPECULATIVE",
            }:
                raise KernelError(
                    "PLAN_IMPACT_FUTURE_ONLY",
                    "inferred impacts cannot mutate executed or in-flight frozen plans",
                )
            if hypothesis.get("dependency_scope_truncated"):
                raise KernelError(
                    "PLAN_IMPACT_SCOPE_TOO_BROAD",
                    "truncated dependency closure requires a narrower proposal",
                )
            impacted.update(
                item["asset_version_id"]
                for item in [
                    hypothesis["candidate"],
                    *hypothesis.get("declared_dependents", []),
                ]
                if item["execution_scope"] != "EXECUTED"
            )
        resolved.append(
            {
                **disposition,
                "relation_status": "AUTHORITY_CONFIRMED"
                if outcome == "CONFIRMED"
                else "DISPROVEN"
                if outcome == "FALSE_POSITIVE"
                else "UNVERIFIED",
            }
        )
    if len(impacted) > DISCOVERY_POLICY["impact_limit"]:
        raise KernelError(
            "PLAN_IMPACT_SCOPE_TOO_BROAD",
            "confirmed impact union exceeds the bounded policy",
        )
    for hypothesis_id, hypothesis in hypotheses.items():
        if hypothesis_id not in seen:
            resolved.append(
                {
                    "hypothesis_id": hypothesis_id,
                    "disposition": hypothesis["default_disposition"],
                    "relation_status": "UNVERIFIED",
                    "rationale": "no Authority confirmation; no inferred mutation",
                }
            )
    return resolved


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
