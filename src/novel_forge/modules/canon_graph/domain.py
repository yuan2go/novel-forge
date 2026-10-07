from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Protocol

from novel_forge.modules.command_kernel.errors import KernelError
from .world_reconciliation import bind_world_event_lineage, validate_observed_world_changes
from novel_forge.modules.narrative_state.contracts import (
    atomize_character_knowledge_changes,
    normalize_character_belief_changes,
)


SEMANTIC_CHANGE_FIELDS = {
    "world_state_changes": "world_state",
    "faction_state_changes": "faction_state",
    "location_state_changes": "location_state",
    "consequence_changes": "consequence_state",
    "conflict_state_changes": "conflict_state",

    "canon_assertion_candidates": "canon_fact",
    "character_state_changes": "character_state",
    "relationship_changes": "relationship_state",
    "timeline_event_candidates": "timeline_event",
    "foreshadow_changes": "foreshadow_state",
    "promise_changes": "reader_promise",
    "obligation_changes": "narrative_obligation",
    "reward_changes": "reward_event",
    "world_rule_usages": "world_rule",
    "power_state_changes": "power_state",
    "plot_thread_changes": "plot_thread",
    "resource_state_changes": "resource_state",
    "narrative_pattern_fingerprints": "narrative_pattern_fingerprints",
    "theme_movements": "theme_movements",
    "antagonist_pressure_changes": "antagonist_pressure_changes",
    "character_knowledge_changes": "character_knowledge",
    "character_belief_changes": "character_belief",
    "character_arc_changes": "character_arc",
    "arc_state_changes": "arc_state",
    "disclosure_events": "disclosure_event",
}

# WHY: Provider response keys are an extraction API, not Narrative State identity.
# Keep this translation explicit so the Canon proposal can use the shared v2
# state-kind vocabulary without silently changing the provider boundary.
PROVIDER_SEMANTIC_CHANGE_FIELDS = {
    "world_state_changes": "world_state_changes",
    "faction_state_changes": "faction_state_changes",
    "location_state_changes": "location_state_changes",
    "consequence_changes": "consequence_changes",
    "conflict_state_changes": "conflict_state_changes",

    "canon_assertion_candidates": "canon_facts",
    "character_state_changes": "character_state_changes",
    "relationship_changes": "relationship_changes",
    "timeline_event_candidates": "timeline_events",
    "foreshadow_changes": "foreshadow_changes",
    "promise_changes": "promise_changes",
    "obligation_changes": "obligation_changes",
    "reward_changes": "reward_changes",
    "world_rule_usages": "world_rule_usages",
    "power_state_changes": "power_state_changes",
    "plot_thread_changes": "plot_thread_changes",
    "resource_state_changes": "resource_state_changes",
    "narrative_pattern_fingerprints": "narrative_pattern_fingerprints",
    "theme_movements": "theme_movements",
    "antagonist_pressure_changes": "antagonist_pressure_changes",
    "character_knowledge_changes": "character_knowledge_changes",
    "character_belief_changes": "character_belief_changes",
    "character_arc_changes": "character_arc_changes",
    "arc_state_changes": "arc_state_changes",
    "disclosure_events": "disclosure_events",
}

HIGH_IMPACT_CHANGE_TYPES = {
    "identity_revelation", "major_relationship_change", "unique_item_destruction",
    "major_faction_ownership_change", "major_secret_disclosure",
    "character_death",
    "entity_merge",
    "world_rule_change",
    "major_power_jump",
    "main_goal_change",
    "foreshadow_abandoned",
    "promise_abandoned",
}


class CanonSemanticProviderPort(Protocol):

    external_effect_backed: bool

    def extract(
        self,
        *,
        project_id: str,
        revision_asset_version_id: str,
        text: str,
        previous_state_refs: tuple[str, ...],
    ) -> dict[str, Any]: ...


def extract_canon_candidates(
    *,
    project_id: str,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    context_bundle_version_id: str,
    provider_extraction: dict[str, Any] | None = None,
    operator_annotations: Iterable[dict[str, Any]] = (),
    work_requirements: bool = False,
) -> dict[str, Any]:
    if not all((project_id, revision_asset_version_id, context_bundle_version_id)):
        raise KernelError(
            "CANON_EXTRACTION_INPUT_INVALID", "versioned extraction lineage is required"
        )
    text = str(revision.get("text") or "").strip()
    if not text:
        raise KernelError(
            "CANON_EXTRACTION_INPUT_INVALID", "accepted revision text is required"
        )
    annotations = tuple(operator_annotations)
    raw_arc_evidence = [
        dict(item)
        for item in (
            (provider_extraction or {}).get("arc_evidence")
            or revision.get("arc_evidence")
            or ()
        )
        if isinstance(item, dict)
    ]
    raw_realization_evidence = [
        dict(item)
        for item in (
            (provider_extraction or {}).get("realization_evidence")
            or revision.get("realization_evidence")
            or ()
        )
        if isinstance(item, dict)
    ]
    assertions = list(revision.get("canon_assertions", []))
    # COMPATIBILITY: Legacy revision identity was a Canon fact; new identity stays in lineage.
    if not work_requirements:
        assertions.append(
            {
                "subject": f"chapter:{revision['chapter']}",
                "predicate": "accepted_revision_digest",
                "object": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "effective_from_chapter": int(revision["chapter"]),
                "evidence_source": "deterministic_revision_digest",
            }
        )
    for item in assertions:
        if not all(
            str(item.get(key) or "").strip()
            for key in ("subject", "predicate", "object")
        ):
            raise KernelError(
                "CANON_ASSERTION_INVALID",
                "canon assertion requires subject/predicate/object",
            )
    changes: dict[str, list[dict[str, Any]]] = {
        "world_state_changes": list(revision.get("world_state_changes", [])),
        "faction_state_changes": list(revision.get("faction_state_changes", [])),
        "location_state_changes": list(revision.get("location_state_changes", [])),
        "consequence_changes": list(revision.get("consequence_changes", [])),
        "conflict_state_changes": list(revision.get("conflict_state_changes", [])),

        "canon_assertion_candidates": assertions,
        "character_state_changes": list(revision.get("character_state_changes", [])),
        "relationship_changes": list(revision.get("relationship_changes", [])),
        "timeline_event_candidates": list(revision.get("timeline_events", [])),
        "foreshadow_changes": list(revision.get("foreshadow_changes", [])),
        "promise_changes": list(revision.get("promise_changes", [])),
        "obligation_changes": list(revision.get("obligation_changes", [])),
        "reward_changes": list(revision.get("reward_changes", [])),
        "world_rule_usages": list(revision.get("world_rule_usages", [])),
        "power_state_changes": list(revision.get("power_state_changes", [])),
        "plot_thread_changes": list(revision.get("plot_thread_changes", [])),
        "resource_state_changes": list(revision.get("resource_state_changes", [])),
        "narrative_pattern_fingerprints": list(
            revision.get("narrative_pattern_fingerprints", [])
        ),
        "theme_movements": list(revision.get("theme_movements", [])),
        "antagonist_pressure_changes": list(
            revision.get("antagonist_pressure_changes", [])
        ),
        "character_knowledge_changes": list(
            revision.get("character_knowledge_changes", [])
        ),
        "character_belief_changes": list(revision.get("character_belief_changes", [])),
        "character_arc_changes": list(revision.get("character_arc_changes", [])),
        "arc_state_changes": list(revision.get("arc_state_changes", [])),
        "reader_knowledge_changes": [],
        "disclosure_events": list(revision.get("disclosure_events", [])),
    }
    _merge_semantic_changes(
        changes, provider_extraction or {}, source="provider_semantic_extractor"
    )
    _merge_operator_annotations(changes, annotations)
    _normalize_resource_changes(changes["resource_state_changes"])
    changes["character_knowledge_changes"] = atomize_character_knowledge_changes(
        changes["character_knowledge_changes"]
    )
    changes["character_belief_changes"] = normalize_character_belief_changes(
        changes["character_belief_changes"]
    )
    changes["reader_knowledge_changes"] = _derive_reader_knowledge_changes(
        changes["disclosure_events"]
    )
    evidence_changes = {
        key: [
            _with_extraction_evidence(
                item,
                text=text,
                revision_asset_version_id=revision_asset_version_id,
                default_extractor=(
                    "deterministic_revision_digest"
                    if item.get("predicate") == "accepted_revision_digest"
                    else "revision_structured_field"
                ),
            )
            for item in values
        ]
        for key, values in changes.items()
    }
    approval_required = [
        {"change_field": field, "change": item}
        for field, values in evidence_changes.items()
        for item in values
        if item.get("approval_requirement") == "REQUIRED"
    ]
    semantic_count = sum(
        len(values)
        for key, values in evidence_changes.items()
        if key != "canon_assertion_candidates"
    ) + sum(
        1
        for item in evidence_changes["canon_assertion_candidates"]
        if item.get("predicate") != "accepted_revision_digest"
    )
    return {
        "project_id": project_id,
        "chapter": int(revision["chapter"]),
        "revision_asset_version_id": revision_asset_version_id,
        "context_bundle_version_id": context_bundle_version_id,
        **evidence_changes,
        "extraction_source": (
            "hybrid"
            if provider_extraction or annotations
            else "deterministic_extractor"
        ),
        "extractor_evidence": {
            "deterministic": True,
            "provider": bool(provider_extraction),
            "operator_annotation": bool(annotations),
        },
        "approval_required_changes": approval_required,
        "semantic_change_count": semantic_count,
        "digest_identity_only": semantic_count == 0,
        "semantic_coverage": "INSUFFICIENT" if semantic_count == 0 else "EXTRACTED",
        "provider_assertions_optional": True,
        "arc_evidence": raw_arc_evidence,
        "realization_evidence": raw_realization_evidence,
        "canon_extraction_contract_version": "canon-semantic-extraction-v6" if work_requirements else "canon-semantic-extraction-v5",
        **({"revision_text_hash": "sha256:" + hashlib.sha256(text.encode()).hexdigest()} if work_requirements else {}),
    }


def build_canon_update(
    *,
    project_id: str,
    revision: dict[str, Any] | None = None,
    revision_asset_version_id: str,
    context_bundle_version_id: str,
    existing_facts: Iterable[dict[str, Any]] = (),
    extraction: dict[str, Any] | None = None,
    historical_state: dict[str, list[dict[str, Any]]] | None = None,
    planned_execution: dict[str, Any] | None = None,
    identity_profiles: Iterable[dict[str, Any]] = (),
    validation_contract: str = "LEGACY_V1",
    reader_observation_lineage: bool = False,
) -> dict[str, Any]:
    if not all((project_id, revision_asset_version_id, context_bundle_version_id)):
        raise KernelError("CANON_INPUT_INVALID", "versioned canon lineage is required")
    if extraction is None:
        if revision is None:
            raise KernelError(
                "CANON_EXTRACTION_REQUIRED", "Canon reduction requires extraction"
            )
        extraction = extract_canon_candidates(
            project_id=project_id,
            revision=revision,
            revision_asset_version_id=revision_asset_version_id,
            context_bundle_version_id=context_bundle_version_id,
        )
    if extraction.get("project_id") != project_id:
        raise KernelError(
            "CROSS_PROJECT_REFERENCE", "Canon extraction belongs to another project"
        )
    if extraction.get("grounding"):
        from .grounding import text_hash
        binding = extraction["grounding"]
        if (binding.get("semantic_status") != "SUPPORTED_CANDIDATE"
            or binding.get("candidate_asset_version_id") != revision_asset_version_id
            or binding.get("text_hash") != text_hash(str((revision or {}).get("text") or ""))
            or binding.get("context_asset_version_id") != context_bundle_version_id):
            raise KernelError("CANON_GROUNDING_IDENTITY_MISMATCH", "Canon reduction requires support bound to the final candidate and Context")
    chapter = int(extraction["chapter"])
    state = {key: list(values) for key, values in (historical_state or {}).items()}
    previous = [*existing_facts, *state.get("canon_snapshot", [])]
    facts = [
        _normalize_fact(item, chapter, revision_asset_version_id)
        for item in extraction.get("canon_assertion_candidates", [])
    ]
    deterministic_validation = validate_deterministic_continuity(
        chapter=chapter,
        historical_state=state,
        extraction=extraction,
        planned_execution=planned_execution,
        revision_text=str((revision or {}).get("text") or ""),
        identity_profiles=identity_profiles,
        validation_contract=validation_contract,
        reader_observation_lineage=reader_observation_lineage,
    )
    expected_realization_ids = {
        str(item.get("event_id") or "")
        for item in (
            (planned_execution or {}).get("narrative_realization") or {}
        ).get("events")
        or ()
        if isinstance(item, dict) and str(item.get("event_id") or "")
    }
    actual_realization_ids = [
        str(item.get("planned_event_id") or "")
        for item in extraction.get("realization_evidence") or ()
        if isinstance(item, dict)
    ]
    if (
        len(actual_realization_ids) != len(set(actual_realization_ids))
        or any(item not in expected_realization_ids for item in actual_realization_ids)
    ):
        raise KernelError(
            "CANON_REALIZATION_EVIDENCE_INVALID",
            "Canon extraction realization evidence is outside the Frozen Chapter slice",
        )
    conflicts = _fact_conflicts(previous, facts)
    conflicts.extend(deterministic_validation["violations"])
    if (
        extraction.get("approval_required_changes")
        and not extraction.get("high_impact_approval", {}).get("status") == "APPROVED"
    ):
        conflicts.append(
            _conflict(
                "HIGH_IMPACT_SEMANTIC_CHANGE_REQUIRES_APPROVAL",
                state,
                extraction.get("approval_required_changes"),
                "approve or reject each high-impact semantic change before reduction",
            )
        )
    state_changes = _narrative_state_changes(extraction, facts)
    if not any(item["severity"] == "blocking" for item in conflicts):
        bind_world_event_lineage(state_changes, reader_observation_lineage=reader_observation_lineage)
    _bind_narrative_entity_versions(state_changes, state)
    return {
        "project_id": project_id,
        "chapter": chapter,
        "source_asset_version_id": revision_asset_version_id,
        **({"grounding": dict(extraction["grounding"])} if extraction.get("grounding") else {}),
        "context_bundle_version_id": context_bundle_version_id,
        "facts": facts,
        "conflicts": conflicts,
        "deterministic_validation": deterministic_validation,
        "gate": "BLOCKED"
        if any(item["severity"] == "blocking" for item in conflicts)
        else "PASSED",
        "historical_input_version_ids": sorted(
            {
                str(item.get("asset_version_id"))
                for values in state.values()
                for item in values
                if item.get("asset_version_id")
            }
        ),
        "state_changes": state_changes,
        "arc_evidence": [
            dict(item)
            for item in extraction.get("arc_evidence") or ()
            if isinstance(item, dict)
        ],
        "realization_evidence": [
            dict(item)
            for item in extraction.get("realization_evidence") or ()
            if isinstance(item, dict)
        ],
        "rebuildable": True,
        "rollback_aware": True,
        "canon_contract_version": "canon-update-domain-v7",
    }


def _normalize_fact(item: dict[str, Any], chapter: int, source: str) -> dict[str, Any]:
    subject = str(item.get("subject") or "").strip()
    predicate = str(item.get("predicate") or "").strip()
    object_value = str(item.get("object") or "").strip()
    if not all((subject, predicate, object_value)):
        raise KernelError(
            "CANON_ASSERTION_INVALID",
            "canon assertion requires subject/predicate/object",
        )
    return {
        "subject": subject,
        "predicate": predicate,
        "object": object_value,
        "effective_from_chapter": int(item.get("effective_from_chapter") or chapter),
        "source_asset_version_id": source,
        "supersedes_event_id": str(item.get("supersedes_event_id") or ""),
        "extraction_evidence": dict(item.get("extraction_evidence") or {}),
        **{key: item[key] for key in ("claim_kind", "grounded_claim_id") if key in item},
        "confidence": float(item.get("confidence", 0.0)),
        "coverage": str(item.get("coverage") or "EXPLICIT"),
    }


def _merge_semantic_changes(
    target: dict[str, list[dict[str, Any]]],
    provider: dict[str, Any],
    *,
    source: str,
) -> None:
    for target_field, provider_field in PROVIDER_SEMANTIC_CHANGE_FIELDS.items():
        values = provider.get(provider_field, [])
        if not isinstance(values, list):
            raise KernelError(
                "CANON_PROVIDER_OUTPUT_INVALID",
                f"provider semantic field {provider_field} must be an array",
            )
        target[target_field].extend(
            {**dict(item), "extractor_type": source}
            for item in values
            if isinstance(item, dict)
        )


def _merge_operator_annotations(
    target: dict[str, list[dict[str, Any]]],
    annotations: Iterable[dict[str, Any]],
) -> None:
    for annotation in annotations:
        field = str(annotation.get("change_field") or "")
        change = annotation.get("change")
        if field not in target or not isinstance(change, dict):
            raise KernelError(
                "CANON_ANNOTATION_INVALID", "operator annotation is not typed"
            )
        target[field].append({**change, "extractor_type": "operator_annotation"})


def _normalize_resource_changes(changes: list[dict[str, Any]]) -> None:

    for change in changes:
        if change.get("delta") is None:
            balance = change.get("balance", change.get("balance_after"))
            if balance is None:
                raise KernelError(
                    "CANON_RESOURCE_BASELINE_INVALID",
                    "initial Resource State requires balance or balance_after",
                )
            change["balance"] = balance
            continue
        before = change.get("balance_before")
        after = change.get("balance_after")
        if (
            before is None
            or after is None
            or float(before) + float(change["delta"]) != float(after)
        ):
            raise KernelError(
                "CANON_RESOURCE_TRANSITION_INVALID",
                "Resource transition requires balance_before + delta = balance_after",
            )


_DISCLOSURE_READER_STATUS = {
    "HINT": "HINTED",
    "PARTIAL": "SUSPECTED",
    "MISDIRECT": "MISDIRECTED",
    "CONFIRM": "KNOWN",
}


def _derive_reader_knowledge_changes(
    disclosures: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:

    by_fact: dict[str, dict[str, Any]] = {}
    for disclosure in disclosures:
        audience = str(disclosure.get("audience") or "").upper()
        mode = str(disclosure.get("disclosure_mode") or "").upper()
        fact_id = str(
            disclosure.get("fact_id") or disclosure.get("proposition_id") or ""
        ).strip()
        if audience not in {"READER", "ALL"} or mode not in _DISCLOSURE_READER_STATUS:
            continue
        if not fact_id:
            raise KernelError(
                "CANON_DISCLOSURE_IDENTITY_INVALID",
                "reader-facing Disclosure requires fact_id or proposition_id",
            )
        by_fact[fact_id] = {
            "fact_id": fact_id,
            "proposition_id": str(disclosure.get("proposition_id") or ""),
            "status": _DISCLOSURE_READER_STATUS[mode],
            "summary": (
                "Reader Knowledge derived from accepted Disclosure "
                f"{disclosure.get('disclosure_id') or fact_id}: {mode}."
            ),
            "effective_from_chapter": disclosure.get("effective_from_chapter"),
            "supersedes_event_id": str(disclosure.get("supersedes_event_id") or ""),
            "disclosure_id": str(disclosure.get("disclosure_id") or ""),
            "disclosure_mode": mode,
            "extractor_type": "derived_disclosure_projection",
            "evidence_start": disclosure.get("evidence_start"),
            "evidence_end": disclosure.get("evidence_end"),
            "confidence": disclosure.get("confidence", 1.0),
            "impact_type": "reader_knowledge_projection",
        }
    return list(by_fact.values())


def _with_extraction_evidence(
    item: dict[str, Any],
    *,
    text: str,
    revision_asset_version_id: str,
    default_extractor: str,
) -> dict[str, Any]:
    extractor = str(item.get("extractor_type") or default_extractor)
    confidence = float(
        item.get(
            "confidence",
            1.0 if extractor == "deterministic_revision_digest" else 0.8,
        )
    )
    start = int(item.get("evidence_start", -1))
    end = int(item.get("evidence_end", -1))
    excerpt = text[start:end] if 0 <= start < end <= len(text) else ""
    impact_type = str(item.get("impact_type") or "")
    inferred_major = (
        str(item.get("life_status") or "").upper() == "DEAD"
        or (item.get("character_id") and str(item.get("status") or "").upper() == "DEAD")
        or item.get("identity_revelation") is True
        or (item.get("unique") is True and str(item.get("status") or "").upper() == "DESTROYED")
    )
    approval_required = impact_type in HIGH_IMPACT_CHANGE_TYPES or confidence < 0.65 or bool(inferred_major)
    return {
        **item,
        "confidence": confidence,
        "extractor_type": extractor,
        "source_revision_asset_version_id": revision_asset_version_id,
        "extraction_evidence": {
            "span": {"start": start, "end": end},
            "excerpt_digest": (
                "sha256:" + hashlib.sha256(excerpt.encode()).hexdigest()
                if excerpt
                else ""
            ),
            "source_revision_asset_version_id": revision_asset_version_id,
            "provider_id": str(item.get("provider_id") or ""),
            "model_id": str(item.get("model_id") or ""),
            "prompt_version": str(item.get("prompt_version") or ""),
            "previous_state_reference": str(item.get("previous_state_reference") or ""),
        },
        "approval_requirement": "REQUIRED" if approval_required else "NONE",
    }


def _conflict(
    code: str,
    existing: Any,
    candidate: Any,
    recommendation: str,
    *,
    approval: bool = True,
) -> dict[str, Any]:
    return {
        "conflict_code": code,
        "severity": "blocking",
        "existing_version": existing,
        "candidate_version": candidate,
        "evidence": {"existing": existing, "candidate": candidate},
        "recommended_resolution": recommendation,
        "approval_requirement": "REQUIRED" if approval else "NONE",
    }


def _fact_conflicts(
    previous: list[dict[str, Any]], facts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    conflicts = []
    for fact in facts:
        superseded = str(fact.get("supersedes_event_id") or "")
        if superseded and not any(
            (old.get("source_event_id") or old.get("event_id")) == superseded
            and old.get("subject") == fact["subject"]
            and old.get("predicate") == fact["predicate"]
            for old in previous
        ):
            conflicts.append(_conflict(
                "CANON_SUPERSESSION_SOURCE_INVALID", previous, fact,
                "resolve the exact same-entity accepted source in the frozen Book boundary",
                approval=False,
            ))
        for old in previous:
            if (
                old.get("subject") == fact["subject"]
                and old.get("predicate") == fact["predicate"]
                and old.get("object") != fact["object"]
                and not fact["supersedes_event_id"]
            ):
                conflicts.append(
                    _conflict(
                        "FACT_CONTRADICTION",
                        old,
                        fact,
                        "supersede explicitly or revise the chapter",
                    )
                )
    return conflicts


def validate_deterministic_continuity(
    *,
    chapter: int,
    historical_state: dict[str, list[dict[str, Any]]],
    extraction: dict[str, Any],
    planned_execution: dict[str, Any] | None = None,
    revision_text: str = "",
    identity_profiles: Iterable[dict[str, Any]] = (),
    validation_contract: str = "LEGACY_V1",
    reader_observation_lineage: bool = False,
) -> dict[str, Any]:

    if chapter <= 0:
        raise ValueError("chapter must be positive")
    state = {kind: _state_items(values) for kind, values in historical_state.items()}
    world_binding = (planned_execution or {}).get("world_preparation") or {}
    frozen_world = (world_binding.get("frozen_source") or {}).get("reality")
    conflicts: list[dict[str, Any]] = validate_observed_world_changes(
        extraction=extraction, historical_state=historical_state,
        frozen_reality=frozen_world,
        reader_observation_lineage=reader_observation_lineage,
    )
    profiles = tuple(dict(item) for item in identity_profiles)
    if validation_contract not in {"LEGACY_V1","grounded-canon-validation.v2"}:
        raise KernelError("CANON_VALIDATION_CONTRACT_INVALID","Canon validation requires a declared versioned contract")
    identity_conflicts=_deterministic_identity_pronoun_conflicts(revision_text=revision_text,identity_profiles=profiles)
    identity_observations=[]
    if validation_contract=="grounded-canon-validation.v2":
        kept=[]
        for conflict in identity_conflicts:
            observed=conflict['candidate_version']['observed_pronoun']
            inferred=conflict['existing_version']['character_id']
            alternate=observed=='它' or any(observed in profile.get('pronouns',[]) and profile.get('character_id')!=inferred for profile in profiles)
            if alternate:
                identity_observations.append({'status':'NOT_RUN','reason':'AMBIGUOUS_LEADING_PRONOUN_REFERENCE',
                    'inferred_character_id':inferred,**conflict['candidate_version'],'review_required':True})
            else:
                kept.append(conflict)
        identity_conflicts=kept
    conflicts.extend(identity_conflicts)
    _validate_transition_preconditions(
        conflicts,
        state=state,
        extraction=extraction,
    )
    _validate_planned_execution(
        conflicts,
        state=state,
        extraction=extraction,
        planned_execution=planned_execution or {},
        validation_contract=validation_contract,
    )
    for event in extraction.get("timeline_event_candidates", []):
        event_chapter = int(event.get("effective_from_chapter", chapter))
        if event_chapter > chapter:
            conflicts.append(
                _conflict(
                    "FUTURE_STATE_LEAK",
                    {"accepted_chapter": chapter},
                    event,
                    "set the event boundary to the current or an earlier chapter",
                )
            )
        if event_chapter < max(
            [
                int(item.get("effective_from_chapter", item.get("chapter", 0)))
                for item in state.get("timeline_snapshot", [])
            ]
            or [0]
        ):
            conflicts.append(
                _conflict(
                    "TEMPORAL_CONTRADICTION",
                    state.get("timeline_snapshot", []),
                    event,
                    "place the event after the latest frozen timeline boundary",
                )
            )
    for change in extraction.get("character_state_changes", []):
        existing = next(
            (
                item
                for item in state.get("character_state", [])
                if item.get("character_id") == change.get("character_id")
            ),
            None,
        )
        if (
            existing
            and existing.get("canonical_name")
            and change.get("canonical_name")
            and existing["canonical_name"] != change["canonical_name"]
        ):
            conflicts.append(
                _conflict(
                    "CHARACTER_IDENTITY_CONTRADICTION",
                    existing,
                    change,
                    "create an alias/merge proposal instead of changing identity",
                )
            )
        if (
            existing
            and str(existing.get("life_status") or "").upper() == "DEAD"
            and not change.get("resurrection_authorized")
            and (
                str(change.get("life_status") or "").upper() in {"ALIVE", "ACTIVE"}
                or str(change.get("action_state") or "").upper()
                in {"ACTIVE", "ACTING", "PRESENT"}
            )
        ):
            conflicts.append(
                _conflict(
                    "DEAD_CHARACTER_USAGE",
                    existing,
                    change,
                    "record an approved resurrection transition or remove the action",
                )
            )
        if existing:
            known = {str(item) for item in existing.get("known_fact_ids", [])} | {
                str(item) for item in change.get("acquired_fact_ids", [])
            }
            required = {str(item) for item in change.get("requires_fact_ids", [])}
            missing = sorted(required - known)
            if missing:
                conflicts.append(
                    _conflict(
                        "KNOWLEDGE_BOUNDARY_VIOLATION",
                        {"known_fact_ids": sorted(known)},
                        {**change, "missing_fact_ids": missing},
                        "bind prior knowledge acquisition evidence before the action",
                    )
                )
    for change in extraction.get("relationship_changes", []):
        source_id = str(
            change.get("source_id") or change.get("source_character_id") or ""
        )
        target_id = str(
            change.get("target_id") or change.get("target_character_id") or ""
        )
        if (
            source_id
            and source_id == target_id
            and not change.get("allow_self_relation")
        ):
            conflicts.append(
                _conflict(
                    "GRAPH_INTEGRITY_VIOLATION",
                    {"constraint": "relationship endpoints must differ"},
                    change,
                    "use two distinct entity identifiers",
                )
            )
        existing = next(
            (
                item
                for item in state.get("relationship_state", [])
                if str(item.get("source_id") or item.get("source_character_id") or "")
                == source_id
                and str(item.get("target_id") or item.get("target_character_id") or "")
                == target_id
            ),
            None,
        )
        declared_from = str(change.get("from_state") or "").upper()
        existing_status = str(
            (existing or {}).get("status") or (existing or {}).get("trust_state") or ""
        ).upper()
        if declared_from and existing_status and declared_from != existing_status:
            conflicts.append(
                _conflict(
                    "INVALID_RELATIONSHIP_TRANSITION",
                    existing,
                    change,
                    "set from_state to the accepted relationship state",
                )
            )
        if change.get("trust_state") == "trusted" and change.get("betrayal_unresolved"):
            conflicts.append(
                _conflict(
                    "RELATIONSHIP_CONTRADICTION",
                    state.get("relationship_state", []),
                    change,
                    "add reconciliation evidence or preserve distrust",
                )
            )
    for usage in extraction.get("world_rule_usages", []):
        rule = next(
            (
                item
                for item in state.get("world_rule", [])
                if item.get("rule_id") == usage.get("rule_id")
            ),
            None,
        )
        if rule and usage.get("state") in set(rule.get("forbidden_states", [])):
            conflicts.append(
                _conflict(
                    "WORLD_RULE_CONTRADICTION",
                    rule,
                    usage,
                    "preserve the accepted rule or record a governed exception with cost",
                )
            )
        if usage.get("exception") and not usage.get("cost"):
            conflicts.append(
                _conflict(
                    "WORLD_RULE_CONTRADICTION",
                    state.get("world_rule", []),
                    usage,
                    "pay the rule exception cost",
                )
            )
    for change in extraction.get("power_state_changes", []):
        existing = next(
            (
                item
                for item in state.get("power_state", [])
                if item.get("character_id") == change.get("character_id")
            ),
            None,
        )
        if (
            existing
            and change.get("from_tier") is not None
            and int(change["from_tier"]) != int(existing.get("tier", 0))
        ):
            conflicts.append(
                _conflict(
                    "POWER_STATE_TRANSITION_INVALID",
                    existing,
                    change,
                    "set from_tier to the accepted power state",
                )
            )
        if (
            str(change.get("transition_kind") or "").upper() == "ADVANCE"
            and existing
            and change.get("tier") is not None
            and int(change["tier"]) <= int(existing.get("tier", 0))
        ):
            conflicts.append(
                _conflict(
                    "POWER_STATE_TRANSITION_INVALID",
                    existing,
                    change,
                    "an ADVANCE transition must increase the accepted tier",
                )
            )
        if change.get("tier_increase") and not change.get("change_reasons"):
            conflicts.append(
                _conflict(
                    "POWER_PROGRESSION_CONTRADICTION",
                    state.get("power_state", []),
                    change,
                    "supply training, equipment, condition, or cost evidence",
                )
            )
    for change in extraction.get("foreshadow_changes", []):
        _validate_lifecycle_transition(
            conflicts,
            state=state.get("foreshadow_state", []),
            change=change,
            identity_key="thread_id",
            code="FORESHADOW_LIFECYCLE_CONTRADICTION",
        )
        if change.get("status") == "PAID" and not change.get("payoff_evidence"):
            conflicts.append(
                _conflict(
                    "FORESHADOW_LIFECYCLE_CONTRADICTION",
                    state.get("foreshadow_state", []),
                    change,
                    "add causal payoff evidence",
                )
            )
    for change in extraction.get("promise_changes", []):
        _validate_lifecycle_transition(
            conflicts,
            state=state.get("reader_promise", []),
            change=change,
            identity_key="promise_id",
            code="PROMISE_LIFECYCLE_CONTRADICTION",
        )
        if change.get("status") == "PAID" and not change.get("payoff_evidence"):
            conflicts.append(
                _conflict(
                    "PROMISE_LIFECYCLE_CONTRADICTION",
                    state.get("reader_promise", []),
                    change,
                    "add reader-visible fulfillment evidence",
                )
            )
    for change in extraction.get("resource_state_changes", []):
        existing = next(
            (
                item
                for item in state.get("resource_state", [])
                if item.get("entity_id") == change.get("entity_id")
                and item.get("resource_id") == change.get("resource_id")
            ),
            None,
        )
        before = change.get("balance_before")
        delta = change.get("delta")
        after = change.get("balance_after")
        invalid = (
            (
                existing is not None
                and before is not None
                and float(before) != float(existing.get("balance", before))
            )
            or (
                before is not None
                and delta is not None
                and after is not None
                and float(before) + float(delta) != float(after)
            )
            or (
                after is not None
                and float(after) < 0
                and not change.get("allow_negative_balance")
            )
        )
        if invalid:
            conflicts.append(
                _conflict(
                    "RESOURCE_STATE_BALANCE_INVALID",
                    existing or {},
                    change,
                    "reconcile balance_before + delta with the accepted resource state",
                )
            )
    disclosures = {
        str(item.get("fact_id") or item.get("proposition_id") or ""): (
            _DISCLOSURE_READER_STATUS.get(
                str(item.get("disclosure_mode") or "").upper()
            )
        )
        for item in extraction.get("disclosure_events", [])
        if str(item.get("audience") or "").upper() in {"READER", "ALL"}
        and _DISCLOSURE_READER_STATUS.get(
            str(item.get("disclosure_mode") or "").upper()
        )
    }
    for change in extraction.get("reader_knowledge_changes", []):
        fact_id = str(change.get("fact_id") or change.get("proposition_id") or "")
        expected_status = disclosures.get(fact_id)
        actual_status = str(change.get("status") or "").upper()
        if expected_status != actual_status:
            conflicts.append(
                _conflict(
                    "READER_KNOWLEDGE_DISCLOSURE_MISMATCH",
                    {
                        "reader_knowledge": "derived from accepted Disclosure only",
                        "expected_status": expected_status,
                    },
                    change,
                    "derive Reader Knowledge status from the accepted Disclosure mode",
                )
            )
    return {
        "gate": "BLOCKED" if conflicts else "PASSED",
        "violations": conflicts,
        "deterministic_rule_count": 15 + int(bool(profiles)),
        "used_text_heuristics": False,
        "surface_identity_check_applied": bool(profiles and revision_text),
        "semantic_judgment_required": [
            "CHARACTER_MOTIVATION",
            "EMOTIONAL_PLAUSIBILITY",
            "OOC",
            "EXPECTED_EXIT_STATE",
        ],
        "contract_version": "deterministic-continuity-v4" if validation_contract=="grounded-canon-validation.v2" else "deterministic-continuity-v3",
        **({'validation_contract':validation_contract,'identity_reference_observations':identity_observations,
            'identity_reference_check_status':'PARTIAL' if identity_observations else 'EXECUTED',
            'deterministic_rule_count':15+int(bool(profiles) and not identity_observations),
            'used_text_heuristics':bool(profiles and revision_text),
            'semantic_judgment_required':['CHARACTER_MOTIVATION','EMOTIONAL_PLAUSIBILITY','OOC','EXPECTED_EXIT_STATE','CHARACTER_COREFERENCE']}
            if validation_contract=="grounded-canon-validation.v2" else {}),
    }


_CHINESE_THIRD_PERSON_PRONOUNS = frozenset({"他", "她", "它"})
_LEADING_PRONOUN = re.compile(
    r"^[\s#>*\-—“”‘’\"'（(]*([他她它])(?=[\u3400-\u9fff])"
)


def _deterministic_identity_pronoun_conflicts(
    *, revision_text: str, identity_profiles: tuple[dict[str, Any], ...]
) -> list[dict[str, Any]]:

    if not revision_text or not identity_profiles:
        return []
    normalized: list[dict[str, Any]] = []
    alias_owners: dict[str, str] = {}
    for raw in identity_profiles:
        character_id = str(raw.get("character_id") or raw.get("entity_id") or "").strip()
        canonical_name = str(
            raw.get("canonical_name") or raw.get("name") or ""
        ).strip()
        aliases = list(
            dict.fromkeys(
                value
                for item in [canonical_name, *(raw.get("aliases") or [])]
                if (value := str(item or "").strip())
            )
        )
        pronouns = {
            str(item or "").strip()
            for item in raw.get("pronouns") or ()
            if str(item or "").strip()
        }
        if not character_id or not canonical_name or not aliases or not pronouns:
            continue
        profile = {
            **raw,
            "character_id": character_id,
            "canonical_name": canonical_name,
            "aliases": aliases,
            "pronouns": sorted(pronouns),
        }
        for alias in aliases:
            owner = alias_owners.get(alias)
            if owner is not None and owner != character_id:
                # WHY: Ambiguous aliases are deliberately excluded instead of guessed.
                alias_owners[alias] = ""
            else:
                alias_owners[alias] = character_id
        normalized.append(profile)
    profiles_by_id = {str(item["character_id"]): item for item in normalized}
    active: dict[str, Any] | None = None
    active_age = 0
    conflicts: list[dict[str, Any]] = []
    units = [
        item.strip()
        for item in re.split(r"(?:\r?\n)+|(?<=[。！？!?])", revision_text)
        if item.strip()
    ]
    for unit in units:
        leading = _LEADING_PRONOUN.match(unit)
        if leading and active is not None and active_age <= 1:
            observed = leading.group(1)
            expected = set(active["pronouns"]) & _CHINESE_THIRD_PERSON_PRONOUNS
            if expected and observed not in expected:
                excerpt = unit[:160]
                conflicts.append(
                    _conflict(
                        "CHARACTER_IDENTITY_PRONOUN_CONTRADICTION",
                        {
                            "character_id": active["character_id"],
                            "canonical_name": active["canonical_name"],
                            "aliases": list(active["aliases"]),
                            "pronouns": list(active["pronouns"]),
                            "source_asset_version_id": str(
                                active.get("source_asset_version_id") or ""
                            ),
                        },
                        {
                            "observed_pronoun": observed,
                            "excerpt": excerpt,
                        },
                        "revise the surface identity or change the governed Character identity contract",
                        approval=False,
                    )
                )
        matched_ids = {
            owner
            for alias, owner in alias_owners.items()
            if owner and alias in unit
        }
        if len(matched_ids) == 1:
            active = profiles_by_id[next(iter(matched_ids))]
            active_age = 0
        elif len(matched_ids) > 1:
            active = None
            active_age = 0
        elif active is not None:
            active_age += 1
            if active_age > 1:
                active = None
                active_age = 0
    return conflicts


def _state_items(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for item in values:
        facts = item.get("facts")
        if isinstance(facts, list):
            flattened.extend(
                {**fact, "asset_version_id": item.get("asset_version_id", "")}
                for fact in facts
                if isinstance(fact, dict)
            )
        else:
            flattened.append(item)
    return flattened


_TRANSITION_PRECONDITION_SPECS = (
    ("character_state_changes", ("character_state",), (("character_id",),)),
    (
        "relationship_changes",
        ("relationship_state",),
        (
            ("source_id", "source_character_id"),
            ("target_id", "target_character_id"),
        ),
    ),
    ("timeline_event_candidates", ("timeline_snapshot",), (("event_id",),)),
    (
        "foreshadow_changes",
        ("foreshadow_state", "narrative_obligation"),
        (("entity_id", "foreshadow_id", "thread_id", "obligation_id"),),
    ),
    (
        "promise_changes",
        ("reader_promise", "narrative_obligation"),
        (("promise_id", "obligation_id"),),
    ),
    (
        "obligation_changes",
        ("narrative_obligation",),
        (("obligation_id",),),
    ),
    ("world_rule_usages", ("world_rule",), (("rule_id",),)),
    ("power_state_changes", ("power_state",), (("character_id",),)),
    (
        "plot_thread_changes",
        ("plot_thread", "narrative_obligation"),
        (("thread_id", "obligation_id"),),
    ),
    (
        "resource_state_changes",
        ("resource_state",),
        (("entity_id",), ("resource_id",)),
    ),
    (
        "character_knowledge_changes",
        ("character_knowledge",),
        (("character_id",), ("fact_id", "proposition_id")),
    ),
    (
        "character_belief_changes",
        ("character_belief",),
        (("character_id",), ("proposition_id", "fact_id")),
    ),
    (
        "character_arc_changes",
        ("character_arc",),
        (("character_id",), ("arc_id",)),
    ),
    (
        "antagonist_pressure_changes",
        ("antagonist_state",),
        (("antagonist_id", "entity_id"),),
    ),
)


def _identity_component(item: dict[str, Any], aliases: tuple[str, ...]) -> str:
    return next(
        (str(item[key]) for key in aliases if item.get(key) not in {None, ""}),
        "",
    )


def _validate_transition_preconditions(
    conflicts: list[dict[str, Any]],
    *,
    state: dict[str, list[dict[str, Any]]],
    extraction: dict[str, Any],
) -> None:
    """INVARIANT: Reject narrative CAS claims that are not backed by accepted state.

    ``from_*`` is an Authority compare-and-set precondition, not a description of
    background state inferred from prose or Story Design.  Keeping this check in
    Canon validation prevents an invalid patch from surviving every Chapter gate
    only to fail during Book acceptance.
    """
    for field, state_kinds, identity_aliases in _TRANSITION_PRECONDITION_SPECS:
        accepted = [item for kind in state_kinds for item in state.get(kind, [])]
        for change in extraction.get(field, []):
            declared = tuple(
                (from_key, current_key)
                for from_key, current_key in (
                    ("from_status", "status"),
                    ("from_stance", "stance"),
                    ("from_state", "state"),
                    ("from_stage", "stage"),
                    ("from_tier", "tier"),
                )
                if from_key in change
            )
            if not declared:
                continue
            identity = tuple(
                _identity_component(change, aliases) for aliases in identity_aliases
            )
            existing = next(
                (
                    item
                    for item in accepted
                    if tuple(
                        _identity_component(item, aliases)
                        for aliases in identity_aliases
                    )
                    == identity
                ),
                None,
            )
            if existing is None:
                conflicts.append(
                    _conflict(
                        "NARRATIVE_TRANSITION_BASELINE_MISSING",
                        None,
                        change,
                        "omit from_* for a first occurrence or bind the accepted Story State baseline",
                    )
                )
                continue
            mismatches = [
                from_key
                for from_key, current_key in declared
                if current_key not in existing
                or str(change[from_key]) != str(existing[current_key])
            ]
            if mismatches:
                conflicts.append(
                    _conflict(
                        "NARRATIVE_TRANSITION_PRECONDITION_FAILED",
                        existing,
                        change,
                        "set every from_* field to the exact accepted Story State value",
                    )
                )


def _validate_planned_execution(
    conflicts: list[dict[str, Any]],
    *,
    state: dict[str, list[dict[str, Any]]],
    extraction: dict[str, Any],
    planned_execution: dict[str, Any],
    validation_contract: str = "LEGACY_V1",
) -> None:

    if not planned_execution:
        return
    actual_by_kind = _narrative_state_changes(extraction, [])
    for planned in planned_execution.get("required_state_transitions") or ():
        if not isinstance(planned, dict):
            continue
        state_kind = str(planned.get("state_kind") or "")
        entity_key = str(planned.get("entity_key") or "")
        candidates = [
            item
            for item in actual_by_kind.get(state_kind, [])
            if entity_key in _candidate_entity_keys(state_kind, item)
        ]
        if not candidates:
            conflicts.append(
                _conflict(
                    "PLANNED_STATE_TRANSITION_MISSING",
                    planned,
                    None,
                    "extract the planned transition from the accepted chapter or revise the future plan",
                )
            )
            continue
        expected_from = str(planned.get("from_state") or "")
        expected_to = str(planned.get("to_state") or "")
        accepted_candidates = [
            item
            for item in state.get(state_kind, [])
            if entity_key in _candidate_entity_keys(state_kind, item)
        ]

        def value_matches(item,expected):
            return _transition_value(item,prefix="to")==expected or (
                validation_contract=="grounded-canon-validation.v2" and state_kind=='character_knowledge'
                and item.get('status')=='KNOWN' and bool(expected) and item.get('summary')==expected)

        def matches(item: dict[str, Any]) -> bool:
            if not value_matches(item,expected_to):
                return False
            actual_from = _transition_value(item, prefix="from")
            if not accepted_candidates:
                return not actual_from
            baseline_matches = any(
                value_matches(accepted,expected_from)
                for accepted in accepted_candidates
            )
            # INVARIANT: The frozen execution plan owns the compare-and-set precondition.
            # Provider extraction may repeat that precondition, but does not need
            # to duplicate it when the exact accepted baseline is already bound.
            # A repeated value must still agree, so extraction cannot override
            # either the plan or accepted Story State.
            allowed_from={"",expected_from}
            if validation_contract=="grounded-canon-validation.v2" and state_kind=='character_knowledge':
                allowed_from.update(_current_state_value(a) for a in accepted_candidates if value_matches(a,expected_from))
            return baseline_matches and actual_from in allowed_from

        if not any(matches(item) for item in candidates):
            conflicts.append(
                _conflict(
                    "PLANNED_STATE_TRANSITION_MISMATCH",
                    planned,
                    candidates,
                    "align the extracted from/to state with the frozen Chapter execution plan",
                )
            )

    actual_disclosures = [
        item
        for item in extraction.get("disclosure_events", [])
        if isinstance(item, dict)
    ]
    for planned in planned_execution.get("disclosures") or ():
        if not isinstance(planned, dict):
            continue
        mode = str(planned.get("mode") or "").upper()
        if mode == "WITHHOLD":
            continue
        disclosure_id = str(planned.get("disclosure_id") or "")
        fact_id = str(planned.get("fact_id") or "")
        matched = next(
            (
                item
                for item in actual_disclosures
                if str(item.get("disclosure_id") or "") == disclosure_id
                and str(item.get("fact_id") or item.get("proposition_id") or "")
                == fact_id
                and str(item.get("audience") or "").upper()
                == str(planned.get("audience") or "").upper()
                and str(item.get("disclosure_mode") or "").upper() == mode
            ),
            None,
        )
        if matched is None:
            conflicts.append(
                _conflict(
                    "PLANNED_DISCLOSURE_MISSING",
                    planned,
                    actual_disclosures,
                    "extract the planned presentation event or revise the future plan",
                )
            )
    actual_reader_knowledge = {
        str(item.get("fact_id") or item.get("proposition_id") or ""): str(
            item.get("status") or ""
        ).upper()
        for item in extraction.get("reader_knowledge_changes", [])
        if isinstance(item, dict)
    }
    for boundary in planned_execution.get("knowledge_boundaries") or ():
        if (
            not isinstance(boundary, dict)
            or str(boundary.get("layer") or "").upper() != "READER_KNOWLEDGE"
        ):
            continue
        fact_id = str(boundary.get("fact_id") or "")
        expected_status = str(boundary.get("status") or "").upper()
        if expected_status in {"WITHHELD", "UNKNOWN"}:
            continue
        if actual_reader_knowledge.get(fact_id) != expected_status:
            conflicts.append(
                _conflict(
                    "PLANNED_READER_KNOWLEDGE_MISMATCH",
                    boundary,
                    {"derived_status": actual_reader_knowledge.get(fact_id)},
                    "derive the planned Reader Knowledge status from the accepted Disclosure mode",
                )
            )


_PLANNED_IDENTITY_FIELDS: dict[str, tuple[tuple[str, ...], ...]] = {
    "canon_fact": (("subject",), ("predicate",)),
    "character_state": (("character_id",),),
    "relationship_state": (
        ("source_id", "source_character_id"),
        ("target_id", "target_character_id"),
    ),
    "timeline_event": (("event_id",),),
    "foreshadow_state": (("thread_id",),),
    "reader_promise": (("promise_id",),),
    "narrative_obligation": (("obligation_id",),),
    "reward_event": (("reward_id",),),
    "world_rule": (("rule_id",),),
    "power_state": (("character_id",),),
    "plot_thread": (("thread_id",),),
    "resource_state": (("entity_id",), ("resource_id",)),
    "character_knowledge": (("character_id",), ("fact_id", "proposition_id")),
    "character_belief": (("character_id",), ("proposition_id", "fact_id")),
    "character_arc": (("character_id",), ("arc_id",)),
    "arc_state": (("arc_id",),),
    "antagonist_state": (("antagonist_id", "entity_id"),),
    "reader_knowledge": (("fact_id", "proposition_id"),),
    "disclosure_event": (("disclosure_id",),),
}

_HISTORICAL_STATE_KIND = {
    "canon_fact": "canon_snapshot",
    "timeline_event": "timeline_snapshot",
    "reward_event": "reward_ledger",
}


def _candidate_entity_keys(state_kind: str, item: dict[str, Any]) -> set[str]:
    # WHY: Provider extraction schemas expose ``entity_id`` as the stable generic
    # identity for state kinds whose domain-specific aliases vary.  Treat it as
    # an exact Authority identity before constructing composite aliases; this
    # keeps Chapter execution reconciliation aligned with the planner's frozen
    # entity_key without weakening compare-and-set value checks.
    direct = str(item.get("entity_key") or item.get("entity_id") or "")
    components = [
        _identity_component(item, aliases)
        for aliases in _PLANNED_IDENTITY_FIELDS.get(state_kind, ())
    ]
    components = [value for value in components if value]
    keys = {direct} if direct else set()
    if components:
        keys.add(":".join(components))
        keys.add(":".join(value.rsplit(":", 1)[-1] for value in components))
    return keys


def _transition_value(item: dict[str, Any], *, prefix: str) -> str:
    keys = (
        ("from_state", "from_status", "from_stance", "from_stage", "from_tier")
        if prefix == "from"
        else ("state", "status", "stance", "stage", "tier")
    )
    return next(
        (str(item[key]) for key in keys if item.get(key) not in {None, ""}),
        "",
    )


def _current_state_value(item: dict[str, Any]) -> str:
    return next(
        (
            str(item[key])
            for key in ("state", "status", "stance", "stage", "tier")
            if item.get(key) not in {None, ""}
        ),
        "",
    )


def _bind_narrative_entity_versions(
    changes: dict[str, list[dict[str, Any]]],
    historical_state: dict[str, list[dict[str, Any]]],
) -> None:

    from novel_forge.modules.narrative_state.contracts import _LEGACY_OBLIGATION_IDENTITY_FIELDS

    for state_kind, items in changes.items():
        accepted = historical_state.get(
            _HISTORICAL_STATE_KIND.get(state_kind, state_kind), []
        )
        for item in items:
            candidate_keys = _candidate_entity_keys(state_kind, item)
            existing = next(
                (
                    prior
                    for prior in accepted
                    if candidate_keys & _candidate_entity_keys(state_kind, prior)
                ),
                None,
            )
            identity_fields = ("obligation_id",) if state_kind == "narrative_obligation" else _LEGACY_OBLIGATION_IDENTITY_FIELDS.get(state_kind, ())
            if identity_fields:
                keys = ("obligation_id", *identity_fields)
                identity = _identity_component(item, keys)
                existing = next((
                    prior for prior in [*historical_state.get("narrative_obligation", []), *accepted]
                    if identity and _identity_component(prior, keys) == identity
                ), None)
            item["entity_version"] = (
                int((existing or {}).get("entity_version") or 0) + 1
            )

    tagged = [(kind, item) for kind, items in changes.items() for item in items if item.get("causal_batch")]
    if tagged:
        from novel_forge.modules.narrative_state.causal_batch import compile_causal_batch
        from novel_forge.modules.narrative_state.contracts import NarrativeStateKind, _identity_for
        nodes = []
        for kind, item in tagged:
            identity = _identity_for(NarrativeStateKind(kind), item, ordinal=0, source="canon_patch")
            prior = next((value for value in historical_state.get(kind, []) if value.get("entity_key") == identity.entity_key), {})
            if kind not in _LEGACY_OBLIGATION_IDENTITY_FIELDS and kind != "narrative_obligation":
                item["entity_version"] = int(prior.get("entity_version") or 0) + 1
            nodes.append({"event_id": "pending:" + item["causal_batch"]["local_id"], "state_kind": kind, "identity": identity.to_dict(), "story_time": item.get("story_time"), "mutation": {"payload": item}})
        accepted_refs = frozenset(ref for _, item in tagged for ref in item["causal_batch"]["depends_on"] if not ref.startswith("local:"))
        batch = compile_causal_batch(nodes, accepted_ids=accepted_refs)
        versions = {}
        for event in batch.ordered:
            item = event["mutation"]["payload"]
            key = (event["state_kind"], event["identity"]["entity_key"])
            item["entity_version"] = versions.get(key, item["entity_version"] - 1) + 1
            versions[key] = item["entity_version"]


def _validate_lifecycle_transition(
    conflicts: list[dict[str, Any]],
    *,
    state: list[dict[str, Any]],
    change: dict[str, Any],
    identity_key: str,
    code: str,
) -> None:
    existing = next(
        (item for item in state if item.get(identity_key) == change.get(identity_key)),
        None,
    )
    if existing is None:
        return
    existing_status = str(existing.get("status") or "OPEN").upper()
    declared_from = str(change.get("from_status") or "").upper()
    next_status = str(change.get("status") or existing_status).upper()
    invalid = (bool(declared_from) and declared_from != existing_status) or (
        existing_status in {"PAID", "ABANDONED", "CANCELLED"}
        and next_status != existing_status
    )
    if invalid:
        conflicts.append(
            _conflict(
                code,
                existing,
                change,
                "transition from the accepted lifecycle state without reopening a terminal item",
            )
        )


def _narrative_state_changes(
    extraction: dict[str, Any], facts: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:

    changes = {
        "world_state": extraction.get("world_state_changes", []),
        "faction_state": extraction.get("faction_state_changes", []),
        "location_state": extraction.get("location_state_changes", []),
        "consequence_state": extraction.get("consequence_changes", []),
        "conflict_state": extraction.get("conflict_state_changes", []),
        "canon_fact": facts,
        "character_state": extraction.get("character_state_changes", []),
        "relationship_state": extraction.get("relationship_changes", []),
        "timeline_event": extraction.get("timeline_event_candidates", []),
        "foreshadow_state": extraction.get("foreshadow_changes", []),
        "reader_promise": extraction.get("promise_changes", []),
        "narrative_obligation": extraction.get("obligation_changes", []),
        "reward_event": extraction.get("reward_changes", []),
        "world_rule": extraction.get("world_rule_usages", []),
        "power_state": extraction.get("power_state_changes", []),
        "plot_thread": extraction.get("plot_thread_changes", []),
        "resource_state": extraction.get("resource_state_changes", []),
        "theme_movement": extraction.get("theme_movements", []),
        "antagonist_state": extraction.get("antagonist_pressure_changes", []),
        "character_knowledge": extraction.get("character_knowledge_changes", []),
        "character_belief": extraction.get("character_belief_changes", []),
        "character_arc": extraction.get("character_arc_changes", []),
        "arc_state": extraction.get("arc_state_changes", []),
        "reader_knowledge": extraction.get("reader_knowledge_changes", []),
        "disclosure_event": extraction.get("disclosure_events", []),
    }
    return {
        key: [dict(item) for item in values]
        for key, values in changes.items()
        if values
    }


__all__ = [
    "build_canon_update",
    "extract_canon_candidates",
    "validate_deterministic_continuity",
    "CanonSemanticProviderPort",
]
