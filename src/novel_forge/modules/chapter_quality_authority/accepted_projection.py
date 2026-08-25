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
CURRENT_CHAPTER_OUTCOME_CONTRACT = "chapter-outcome-v3"
SUPPORTED_CHAPTER_OUTCOME_CONTRACTS = (
    "chapter-outcome-v2",
    CURRENT_CHAPTER_OUTCOME_CONTRACT,
)


def validate_chapter_outcome_contract(value: object) -> str:
    contract = str(value or "")
    if contract not in SUPPORTED_CHAPTER_OUTCOME_CONTRACTS:
        raise KernelError(
            "LONGITUDINAL_QUALITY_OUTCOME_CONTRACT_UNSUPPORTED",
            "accepted Quality projection reads historical ChapterOutcome v2 "
            "or canonical ChapterOutcome v3 only",
        )
    return contract


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
                   quality.content, story.content,
                   acceptance.story_state_asset_version_id,
                   acceptance.canon_snapshot_asset_version_id,
                   canon.content,
                   request.narrative_realization_id,
                   request.narrative_realization_slice_id,
                   request.narrative_realization_contract_digest,
                   realization.content_asset_version_id,
                   realization.contract_digest,
                   COALESCE(realization_coverage.rows, '[]'::jsonb)
            FROM authority_book_chapter_acceptance AS acceptance
            JOIN authority_book_production AS production
              ON production.book_run_id=acceptance.book_run_id
             AND production.project_id=acceptance.project_id
            JOIN authority_book_chapter_request AS request
              ON request.chapter_request_id=acceptance.chapter_request_id
             AND request.project_id=acceptance.project_id
             AND request.book_run_id=acceptance.book_run_id
             AND request.chapter_number=acceptance.chapter_number
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
             AND draft_asset.asset_type IN (
                 'draft_version','best_draft_candidate'
             )
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
            JOIN authority_asset_version AS canon
              ON canon.asset_version_id=acceptance.canon_snapshot_asset_version_id
             AND canon.eligibility='ELIGIBLE'
             AND canon.governance='CLEAR'
            JOIN authority_asset AS canon_asset
              ON canon_asset.asset_id=canon.asset_id
             AND canon_asset.project_id=acceptance.project_id
             AND canon_asset.asset_type='canon_snapshot'
            LEFT JOIN authority_narrative_realization AS realization
              ON realization.realization_id=request.narrative_realization_id
             AND realization.project_id=acceptance.project_id
             AND realization.book_id=production.book_id
             AND acceptance.chapter_number BETWEEN
                 realization.chapter_start AND realization.chapter_end
            LEFT JOIN LATERAL (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'planned_event_id', consumption.planned_event_id,
                        'observed_event_id', consumption.observed_event_id,
                        'coverage_status', consumption.coverage_status,
                        'evidence', consumption.evidence
                    ) ORDER BY consumption.planned_event_id
                ) AS rows
                FROM authority_narrative_realization_consumption AS consumption
                WHERE consumption.acceptance_id=acceptance.acceptance_id
                  AND consumption.chapter_outcome_asset_version_id=
                      acceptance.chapter_outcome_asset_version_id
            ) AS realization_coverage ON TRUE
            WHERE acceptance.project_id=%s
              AND production.book_id=%s
              AND acceptance.status='COMMITTED'
              AND acceptance.chapter_number<=%s
              AND outcome.content->>'contract_version' IN (
                  'chapter-outcome-v2','chapter-outcome-v3'
              )
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
            story_state_asset_version_id=str(row[9]),
            canon_snapshot_asset_version_id=str(row[10]),
            canon_snapshot=dict(row[11]),
            narrative_realization_id=str(row[12] or ""),
            narrative_realization_slice_id=str(row[13] or ""),
            requested_realization_contract_digest=str(row[14] or ""),
            narrative_realization_asset_version_id=str(row[15] or ""),
            narrative_realization_contract_digest=str(row[16] or ""),
            realization_coverage=tuple(dict(item) for item in (row[17] or ())),
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
    story_state_asset_version_id: str,
    canon_snapshot_asset_version_id: str,
    canon_snapshot: dict[str, Any],
    narrative_realization_id: str,
    narrative_realization_slice_id: str,
    requested_realization_contract_digest: str,
    narrative_realization_asset_version_id: str,
    narrative_realization_contract_digest: str,
    realization_coverage: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    outcome_contract = validate_chapter_outcome_contract(
        outcome.get("contract_version")
    )
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
    if story_state.get("contract_version") == "story-state-snapshot-v2" and (
        story_state.get("project_id") != project_id
        or story_state.get("book_id") != book_id
        or story_state.get("based_on_chapter_outcome_asset_version_id")
        != accepted_asset_version_id
    ):
        raise KernelError(
            "LONGITUDINAL_QUALITY_ACCEPTED_LINEAGE_REQUIRED",
            "accepted Story State does not derive from the accepted ChapterOutcome",
        )
    if (
        canon_snapshot.get("contract_version") != "canon-snapshot-v2"
        or canon_snapshot.get("project_id") != project_id
        or canon_snapshot.get("book_id") != book_id
        or int(canon_snapshot.get("accepted_through_chapter") or 0)
        != chapter_number
        or canon_snapshot.get("based_on_chapter_outcome_asset_version_id")
        != accepted_asset_version_id
    ):
        raise KernelError(
            "LONGITUDINAL_QUALITY_ACCEPTED_LINEAGE_REQUIRED",
            "accepted Canon does not derive from the accepted ChapterOutcome",
        )
    if narrative_realization_id and (
        not narrative_realization_asset_version_id
        or not narrative_realization_contract_digest
        or requested_realization_contract_digest
        != narrative_realization_contract_digest
    ):
        raise KernelError(
            "LONGITUDINAL_QUALITY_REALIZATION_LINEAGE_REQUIRED",
            "accepted Quality projection lost its Narrative Realization binding",
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
    state_events = [
        dict(event)
        for event in outcome.get("state_events") or ()
        if isinstance(event, Mapping)
    ]
    effects = [
        effect
        for event in state_events
        for effect in (
            event.get("effects")
            or (event.get("mutation") or {}).get("payload", {}).get("effects")
            or ()
        )
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
    arc_evidence = _arc_evidence(outcome)
    realization_evidence = [
        dict(item)
        for item in outcome.get("realization_evidence") or ()
        if isinstance(item, Mapping)
    ]
    causal_progress_ids = sorted(
        {
            str(item.get("observed_event_id") or "")
            for item in realization_evidence
            if item.get("observation_status") == "OBSERVED"
            and str(item.get("observed_event_id") or "")
            and str(item.get("observed_consequence") or "")
            and (
                item.get("observed_cause_event_ids")
                or item.get("observed_state_deltas")
            )
        }
        | {
            str(event.get("event_id") or "")
            for event in state_events
            if str(event.get("event_id") or "")
            and isinstance(event.get("causality"), Mapping)
            and (event.get("causality") or {}).get("cause_refs")
        }
    )
    irreversible_ids = sorted(
        str(event.get("event_id") or "")
        for event in state_events
        if str(event.get("event_id") or "") and _irreversible_event(event)
    )
    protagonist_decision_ids = sorted(
        {
            _digest(str(item.get("observed_decision") or ""))
            for item in realization_evidence
            if item.get("observation_status") == "OBSERVED"
            and str(item.get("observed_decision") or "")
        }
    )
    antagonist_response_ids = sorted(
        {
            str(event.get("event_id") or "")
            for event in state_events
            if str(event.get("state_kind") or "")
            in {"antagonist_state", "conflict_state"}
            and str(event.get("event_id") or "")
        }
    )
    reader_outcome = _reader_outcome(outcome)
    obligation_states = _obligation_states(story_state)
    repetition_signatures = _semantic_repetition_signatures(
        plan=plan,
        outcome=outcome,
        state_events=state_events,
        realization_evidence=realization_evidence,
        draft_text=str(draft.get("text") or ""),
    )
    return {
        "project_id": project_id,
        "book_id": book_id,
        "chapter_number": chapter_number,
        "acceptance_id": acceptance_id,
        "accepted_asset_version_id": accepted_asset_version_id,
        "acceptance_status": acceptance_status,
        "chapter_outcome_contract_version": outcome_contract,
        "chapter_plan_asset_version_id": str(
            outcome.get("chapter_plan_version_id") or ""
        ),
        "accepted_draft_asset_version_id": str(
            outcome.get("accepted_draft_asset_version_id") or ""
        ),
        "quality_aggregate_asset_version_id": str(
            outcome.get("quality_aggregate_asset_version_id") or ""
        ),
        "story_state_asset_version_id": story_state_asset_version_id,
        "canon_snapshot_asset_version_id": canon_snapshot_asset_version_id,
        "narrative_realization_id": narrative_realization_id,
        "narrative_realization_slice_id": narrative_realization_slice_id,
        "narrative_realization_asset_version_id": (
            narrative_realization_asset_version_id
        ),
        "narrative_realization_contract_digest": (
            narrative_realization_contract_digest
        ),
        "realization_coverage": [dict(item) for item in realization_coverage],
        "activity_event_count": (
            len(state_events)
            + len(outcome.get("scene_outcomes") or ())
            + sum(
                item.get("observation_status") == "OBSERVED"
                for item in arc_evidence
            )
        ),
        "causal_progress_event_ids": causal_progress_ids,
        "irreversible_state_change_ids": irreversible_ids,
        "goal_progress_units": sum(
            int(item.get("progress_units") or 0)
            for item in arc_evidence
            if item.get("observation_status") == "OBSERVED"
        ),
        "obstacle_escalation": bool(antagonist_response_ids)
        or any(
            "PRESSURE" in {
                str(value).upper()
                for value in item.get("effect_dimensions") or ()
            }
            for item in arc_evidence
        ),
        "protagonist_decision_ids": protagonist_decision_ids,
        "antagonist_response_ids": antagonist_response_ids,
        "ending_propulsion": bool(hook),
        "arc_evidence": arc_evidence,
        "obligation_states": obligation_states,
        "semantic_repetition_signatures": repetition_signatures,
        "lexical_fingerprints": _lexical_fingerprints(
            str(draft.get("text") or "")
        ),
        "reader_outcome": reader_outcome,
        "reader_outcome_asset_version_ids": [],
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
        "projection_contract_version": "accepted-quality-observation-v2",
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


def _arc_evidence(outcome: Mapping[str, Any]) -> list[dict[str, Any]]:
    fields = (
        "arc_plan_version_id",
        "observation_status",
        "contribution_kind",
        "progress_units",
        "effect_dimensions",
        "milestone_ids",
        "actual_consequences",
        "obligation_ids",
        "completion_criterion_ids",
        "phase_to",
    )
    return [
        {key: item.get(key) for key in fields}
        for item in outcome.get("arc_evidence") or ()
        if isinstance(item, Mapping)
        and str(item.get("arc_plan_version_id") or "")
    ]


def _irreversible_event(event: Mapping[str, Any]) -> bool:
    mutation = dict(event.get("mutation") or {})
    payload = dict(mutation.get("payload") or {})
    status = str(payload.get("status") or "").upper()
    return bool(
        payload.get("irreversible") is True
        or str(mutation.get("semantics") or "").upper() in {"CLOSE", "DECREMENT"}
        or status
        in {
            "DEAD",
            "DESTROYED",
            "FULFILLED",
            "PAID",
            "CANCELLED",
            "ABANDONED",
        }
        or str(event.get("state_kind") or "")
        in {"payoff_event", "consequence_state"}
    )


def _obligation_states(story_state: Mapping[str, Any]) -> list[dict[str, Any]]:
    current = dict(story_state.get("current_state") or {})
    rows: list[dict[str, Any]] = []
    for raw in current.get("narrative_obligation") or ():
        if not isinstance(raw, Mapping):
            continue
        state = dict(raw.get("state") or {})
        obligation_id = str(
            state.get("obligation_id") or raw.get("entity_key") or ""
        )
        if obligation_id.startswith("obligation_id="):
            obligation_id = obligation_id.removeprefix("obligation_id=")
        if not obligation_id:
            continue
        rows.append(
            {
                "obligation_id": obligation_id,
                "status": str(state.get("status") or "UNKNOWN").upper(),
                "opened_chapter": int(
                    state.get("opened_chapter")
                    or (state.get("introduced_at") or {}).get("chapter")
                    or 0
                ),
                "target_window": dict(state.get("target_window") or {}),
                "development_history": [
                    {"chapter": int(item.get("chapter") or 0)}
                    for item in state.get("development_history") or ()
                    if isinstance(item, Mapping)
                ],
                "payoff_evidence": dict(state.get("payoff_evidence") or {}),
                "actual_payoff": dict(state.get("actual_payoff") or {}),
                "linked_arc_ids": sorted(
                    str(item) for item in state.get("linked_arc_ids") or () if str(item)
                ),
            }
        )
    return sorted(rows, key=lambda item: item["obligation_id"])


def _reader_outcome(outcome: Mapping[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    for raw in outcome.get("reader_state_observations") or ():
        if not isinstance(raw, Mapping):
            continue
        for key in (
            "continue_intent",
            "curiosity",
            "satisfaction",
            "confusion",
            "trust",
            "character_attachment",
            "antagonist_pressure",
            "promise_expectation",
            "payoff_satisfaction",
            "drop_risk",
            "repetition_fatigue",
        ):
            value = raw.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                result[key] = float(value)
    return result


def _semantic_repetition_signatures(
    *,
    plan: Mapping[str, Any],
    outcome: Mapping[str, Any],
    state_events: list[dict[str, Any]],
    realization_evidence: list[dict[str, Any]],
    draft_text: str,
) -> dict[str, list[str]]:
    scenes = [
        dict(item)
        for item in outcome.get("scene_outcomes") or ()
        if isinstance(item, Mapping)
    ]
    reader = [
        dict(item)
        for item in outcome.get("reader_state_observations") or ()
        if isinstance(item, Mapping)
    ]
    state_kinds = sorted(
        str(item.get("state_kind") or "")
        for item in state_events
        if str(item.get("state_kind") or "")
    )
    scene_functions = [
        str(item.get("scene_type") or item.get("scene_function") or "")
        for item in scenes
        if str(item.get("scene_type") or item.get("scene_function") or "")
    ]
    opening = [
        str(item.get("opening_pattern") or "")
        for item in (*scenes, *reader)
        if str(item.get("opening_pattern") or "")
    ]
    ending = [
        str(item.get("ending_pattern") or "")
        for item in (*scenes, *reader)
        if str(item.get("ending_pattern") or "")
    ]
    hook = plan.get("ending_hook") or plan.get("closing_hook") or ""
    hook_kind = (
        str(hook.get("type") or hook.get("pattern") or "")
        if isinstance(hook, Mapping)
        else ""
    )
    structural = _text_structure_signature(draft_text)
    raw: dict[str, list[str]] = {
        "plot_pattern": [_digest("|".join(state_kinds))] if state_kinds else [],
        "conflict_solution": [
            str(item.get("conflict_solution") or item.get("resolution_pattern") or "")
            for item in scenes
            if str(item.get("conflict_solution") or item.get("resolution_pattern") or "")
        ],
        "scene_function": scene_functions,
        "chapter_structure": [
            _digest("|".join((*opening, *scene_functions, *ending)))
        ]
        if opening or scene_functions or ending
        else [],
        "emotional_beat": [
            str(item.get("emotional_beat") or item.get("mood") or "")
            for item in (*scenes, *reader)
            if str(item.get("emotional_beat") or item.get("mood") or "")
        ],
        "dialogue_behavior": [structural["dialogue"]] if structural else [],
        "information_release": [
            str(item.get("event_id") or "")
            for item in state_events
            if str(item.get("state_kind") or "")
            in {"disclosure_event", "reader_knowledge"}
            and str(item.get("event_id") or "")
        ],
        "protagonist_reaction": [
            _digest(str(item.get("observed_decision") or ""))
            for item in realization_evidence
            if str(item.get("observed_decision") or "")
        ],
        "antagonist_response": [
            str(item.get("event_id") or "")
            for item in state_events
            if str(item.get("state_kind") or "")
            in {"antagonist_state", "conflict_state"}
            and str(item.get("event_id") or "")
        ],
        "hook_pattern": [*ending, *([hook_kind] if hook_kind else [])],
        "prose_style": [structural["style"]] if structural else [],
    }
    return {
        dimension: sorted({_digest(value) for value in values if value})
        for dimension, values in raw.items()
    }


def _text_structure_signature(text: str) -> dict[str, str]:
    if not text:
        return {}
    sentences = [
        item.strip() for item in re.split(r"[。！？!?\.]+", text) if item.strip()
    ]
    paragraphs = [item.strip() for item in re.split(r"\n+", text) if item.strip()]
    average = round(sum(len(item) for item in sentences) / max(len(sentences), 1))
    dialogue_turns = sum(
        item.count(mark) for item in paragraphs for mark in ('“', '”', '"')
    )
    return {
        "dialogue": f"dialogue:{min(dialogue_turns, 8)}:paragraphs:{min(len(paragraphs), 8)}",
        "style": f"sentence-bucket:{min(average // 5, 12)}:paragraph-bucket:{min(len(paragraphs), 12)}",
    }


def _lexical_fingerprints(text: str) -> list[str]:
    normalized = re.sub(r"\s+", "", text.lower())
    if not normalized:
        return []
    width = 4 if len(normalized) >= 4 else len(normalized)
    hashes = {
        hashlib.sha256(normalized[index : index + width].encode("utf-8")).hexdigest()[:16]
        for index in range(max(1, len(normalized) - width + 1))
    }
    return [f"sha256:{value}" for value in sorted(hashes)[:64]]


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


__all__ = [
    "CURRENT_CHAPTER_OUTCOME_CONTRACT",
    "SUPPORTED_CHAPTER_OUTCOME_CONTRACTS",
    "load_accepted_quality_observations",
    "validate_chapter_outcome_contract",
]
