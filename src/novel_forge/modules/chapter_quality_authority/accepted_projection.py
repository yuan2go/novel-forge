"""Compact longitudinal Quality projection from committed Book acceptance."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state import project_narrative_load
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


_MAX_ACCEPTED_QUALITY_OBSERVATIONS = 300
_TERMINAL_ARC_STATES = {"CLOSED", "RESOLVED", "FULFILLED", "CANCELLED"}


def load_accepted_quality_observations(
    database_url: str,
    *,
    project_id: str,
    book_id: str,
    accepted_through_chapter: int,
) -> list[dict[str, Any]]:
    """Read exact accepted lineage and discard prose after metric projection."""

    if not database_url or not project_id or not book_id or accepted_through_chapter < 0:
        raise ValueError("accepted Quality projection scope is invalid")
    if accepted_through_chapter == 0:
        return []
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT acceptance.acceptance_id, acceptance.status,
                   acceptance.chapter_number,
                   acceptance.chapter_outcome_asset_version_id,
                   outcome.content, plan.content, draft.content,
                   quality.content, story.content
            FROM authority_book_chapter_acceptance AS acceptance
            JOIN authority_book_production AS production
              ON production.book_run_id=acceptance.book_run_id
             AND production.project_id=acceptance.project_id
            JOIN authority_operation AS acceptance_operation
              ON acceptance_operation.operation_id=acceptance.acceptance_operation_id
             AND acceptance_operation.project_id=acceptance.project_id
             AND acceptance_operation.status='SUCCEEDED'
            JOIN authority_asset_version AS outcome
              ON outcome.asset_version_id=acceptance.chapter_outcome_asset_version_id
             AND outcome.eligibility='ELIGIBLE'
             AND outcome.governance='CLEAR'
            JOIN authority_asset AS outcome_asset
              ON outcome_asset.asset_id=outcome.asset_id
             AND outcome_asset.project_id=acceptance.project_id
             AND outcome_asset.asset_type='chapter_outcome'
            JOIN authority_asset_version AS plan
              ON plan.asset_version_id=outcome.content->>'chapter_plan_version_id'
            JOIN authority_asset AS plan_asset
              ON plan_asset.asset_id=plan.asset_id
             AND plan_asset.project_id=acceptance.project_id
             AND plan_asset.asset_type='chapter_plan'
            JOIN authority_asset_version AS draft
              ON draft.asset_version_id=outcome.content->>'accepted_draft_asset_version_id'
            JOIN authority_asset AS draft_asset
              ON draft_asset.asset_id=draft.asset_id
             AND draft_asset.project_id=acceptance.project_id
             AND draft_asset.asset_type='draft_version'
            JOIN authority_asset_version AS quality
              ON quality.asset_version_id=outcome.content->>'quality_aggregate_asset_version_id'
            JOIN authority_asset AS quality_asset
              ON quality_asset.asset_id=quality.asset_id
             AND quality_asset.project_id=acceptance.project_id
             AND quality_asset.asset_type='quality_score_report'
            JOIN authority_asset_version AS story
              ON story.asset_version_id=acceptance.story_state_asset_version_id
            JOIN authority_asset AS story_asset
              ON story_asset.asset_id=story.asset_id
             AND story_asset.project_id=acceptance.project_id
             AND story_asset.asset_type='story_state_snapshot'
            WHERE acceptance.project_id=%s
              AND production.book_id=%s
              AND acceptance.status='COMMITTED'
              AND acceptance.chapter_number<=%s
              AND outcome.content->>'contract_version'='chapter-outcome-v2'
            ORDER BY acceptance.chapter_number
            LIMIT %s
            """,
            [
                project_id,
                book_id,
                accepted_through_chapter,
                _MAX_ACCEPTED_QUALITY_OBSERVATIONS + 1,
            ],
        )
        rows = uow.cursor.fetchall()
    if len(rows) > _MAX_ACCEPTED_QUALITY_OBSERVATIONS:
        raise KernelError(
            "LONGITUDINAL_QUALITY_HISTORY_REQUIRES_ROLLUP",
            "accepted Quality history exceeds the bounded canonical Book horizon",
        )
    return [
        _observation(
            project_id=project_id,
            book_id=book_id,
            acceptance_id=str(row[0]),
            acceptance_status=str(row[1]),
            chapter_number=int(row[2]),
            accepted_asset_version_id=str(row[3]),
            outcome=dict(row[4]),
            plan=dict(row[5]),
            draft=dict(row[6]),
            quality=dict(row[7]),
            story_state=dict(row[8]),
        )
        for row in rows
    ]


def _observation(
    *,
    project_id: str,
    book_id: str,
    acceptance_id: str,
    acceptance_status: str,
    chapter_number: int,
    accepted_asset_version_id: str,
    outcome: dict[str, Any],
    plan: dict[str, Any],
    draft: dict[str, Any],
    quality: dict[str, Any],
    story_state: dict[str, Any],
) -> dict[str, Any]:
    if (
        outcome.get("project_id") != project_id
        or outcome.get("book_id") != book_id
        or int(outcome.get("chapter_number") or 0) != chapter_number
        or int(story_state.get("accepted_through_chapter") or 0) != chapter_number
    ):
        raise KernelError(
            "LONGITUDINAL_QUALITY_ACCEPTED_LINEAGE_REQUIRED",
            "accepted Quality projection resolved inconsistent Chapter lineage",
        )
    segment = dict(plan.get("narrative_segment_ref") or {})
    active_arcs = sorted(
        {
            str(item.get("arc_plan_version_id") or "")
            for item in plan.get("arc_schedule") or ()
            if isinstance(item, Mapping) and str(item.get("arc_plan_version_id") or "")
        }
    )
    open_arcs = _open_arc_ids(story_state)
    characters = sorted(
        {
            str(item.get("character_id") or item.get("id") or item)
            for field in ("character_participation", "cast")
            for item in plan.get(field) or ()
            if str(
                item.get("character_id") or item.get("id") or ""
                if isinstance(item, Mapping)
                else item
            )
        }
    )
    scene_ids = sorted(
        str(item.get("scene_id") or "")
        for item in plan.get("scene_plan") or ()
        if isinstance(item, Mapping) and str(item.get("scene_id") or "")
    )
    hook = str(
        plan.get("ending_hook")
        or plan.get("closing_hook")
        or (plan.get("reader_experience") or {}).get("exit_question")
        or ""
    )
    payoff_count = sum(
        1
        for item in plan.get("payoffs") or ()
        if isinstance(item, Mapping)
        and str(item.get("action") or "").upper() == "PAYOFF"
    )
    effects = [
        effect
        for event in outcome.get("state_events") or ()
        if isinstance(event, Mapping)
        for effect in event.get("effects") or ()
        if isinstance(effect, Mapping)
    ]
    payoff_count += sum(
        1 for effect in effects if str(effect.get("effect_kind") or "").upper() == "PAYOFF"
    )
    new_world_concepts = sorted(
        {
            str(effect.get("entity_key") or effect.get("fact_id") or "")
            for effect in effects
            if str(effect.get("state_kind") or "")
            in {"world_state", "world_rule", "location_state", "faction_state"}
            and str(effect.get("entity_key") or effect.get("fact_id") or "")
        }
    )
    load = project_narrative_load(story_state=story_state)
    debt_score = (load.get("metrics") or {}).get("narrative_debt_score")
    reward = dict(plan.get("reader_experience") or {}).get("reward_mode")
    reader_reward_count = int(bool(str(reward or ""))) + len(
        outcome.get("reader_state_observations") or ()
    )
    return {
        "project_id": project_id,
        "book_id": book_id,
        "chapter_number": chapter_number,
        "acceptance_id": acceptance_id,
        "accepted_asset_version_id": accepted_asset_version_id,
        "acceptance_status": acceptance_status,
        "volume_id": str(segment.get("volume_plan_version_id") or ""),
        "segment_ids": [str(segment.get("segment_id") or "")]
        if segment.get("segment_id")
        else [],
        "active_arc_ids": active_arcs,
        "open_arc_ids": open_arcs,
        "character_ids": characters,
        "scene_ids": scene_ids,
        "hook_signature": _digest(hook) if hook else "",
        "payoff_count": payoff_count,
        "narrative_debt_score": debt_score,
        "new_world_concept_ids": new_world_concepts,
        "average_sentence_length": _average_sentence_length(
            str(draft.get("text") or "")
        ),
        "reader_reward_count": reader_reward_count,
        "quality_gate": str(quality.get("gate") or ""),
        "projection_contract_version": "accepted-quality-observation-v1",
    }


def _open_arc_ids(story_state: dict[str, Any]) -> list[str]:
    current = dict(story_state.get("current_state") or {})
    return sorted(
        {
            str(item.get("entity_key") or "")
            for kind in ("arc_state", "character_arc", "plot_thread")
            for item in current.get(kind) or ()
            if isinstance(item, Mapping)
            and str(item.get("entity_key") or "")
            and str((item.get("state") or {}).get("status") or "ACTIVE").upper()
            not in _TERMINAL_ARC_STATES
        }
    )


def _average_sentence_length(text: str) -> float | None:
    sentences = [item.strip() for item in re.split(r"[。！？!?\.]+", text) if item.strip()]
    if not sentences:
        return None
    lengths = [len(item.split()) if " " in item else len(item) for item in sentences]
    return round(sum(lengths) / len(lengths), 4)


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = ["load_accepted_quality_observations"]
