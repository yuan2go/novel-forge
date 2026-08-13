"""Storage-free canon extraction, conflict detection, and state reduction."""
from __future__ import annotations

import hashlib
from typing import Any, Iterable, Protocol

from novel_forge.modules.command_kernel.errors import KernelError


SEMANTIC_CHANGE_FIELDS = {
    "canon_assertion_candidates": "canon_fact",
    "character_state_changes": "character_state",
    "relationship_changes": "relationship_state",
    "timeline_event_candidates": "timeline_event",
    "foreshadow_changes": "foreshadow_state",
    "promise_changes": "reader_promise",
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
    "reader_knowledge_changes": "reader_knowledge",
    "disclosure_events": "disclosure_event",
}

# Provider response keys are an extraction API, not Narrative State identity.
# Keep this translation explicit so the Canon proposal can use the shared v2
# state-kind vocabulary without silently changing the provider boundary.
PROVIDER_SEMANTIC_CHANGE_FIELDS = {
    "canon_assertion_candidates": "canon_facts",
    "character_state_changes": "character_state_changes",
    "relationship_changes": "relationship_changes",
    "timeline_event_candidates": "timeline_events",
    "foreshadow_changes": "foreshadow_changes",
    "promise_changes": "promise_changes",
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
    "reader_knowledge_changes": "reader_knowledge_changes",
    "disclosure_events": "disclosure_events",
}

HIGH_IMPACT_CHANGE_TYPES = {
    "character_death",
    "entity_merge",
    "world_rule_change",
    "major_power_jump",
    "main_goal_change",
    "foreshadow_abandoned",
    "promise_abandoned",
}


class CanonSemanticProviderPort(Protocol):
    """Optional provider boundary; implementations must execute via ExternalEffect."""

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
) -> dict[str, Any]:
    """Produce deterministic candidates independently of revision-provider metadata."""
    if not all((project_id, revision_asset_version_id, context_bundle_version_id)):
        raise KernelError("CANON_EXTRACTION_INPUT_INVALID", "versioned extraction lineage is required")
    text = str(revision.get("text") or "").strip()
    if not text:
        raise KernelError("CANON_EXTRACTION_INPUT_INVALID", "accepted revision text is required")
    annotations = tuple(operator_annotations)
    assertions = list(revision.get("canon_assertions", []))
    # Every accepted chapter has a deterministic event assertion, so a real-provider
    # path never silently produces an empty Canon update when optional structured
    # assertions are absent.
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
        if not all(str(item.get(key) or "").strip() for key in ("subject", "predicate", "object")):
            raise KernelError("CANON_ASSERTION_INVALID", "canon assertion requires subject/predicate/object")
    changes: dict[str, list[dict[str, Any]]] = {
        "canon_assertion_candidates": assertions,
        "character_state_changes": list(revision.get("character_state_changes", [])),
        "relationship_changes": list(revision.get("relationship_changes", [])),
        "timeline_event_candidates": list(revision.get("timeline_events", [])),
        "foreshadow_changes": list(revision.get("foreshadow_changes", [])),
        "promise_changes": list(revision.get("promise_changes", [])),
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
        "character_belief_changes": list(
            revision.get("character_belief_changes", [])
        ),
        "character_arc_changes": list(revision.get("character_arc_changes", [])),
        "arc_state_changes": list(revision.get("arc_state_changes", [])),
        "reader_knowledge_changes": list(
            revision.get("reader_knowledge_changes", [])
        ),
        "disclosure_events": list(revision.get("disclosure_events", [])),
    }
    _merge_semantic_changes(changes, provider_extraction or {}, source="provider_semantic_extractor")
    _merge_operator_annotations(changes, annotations)
    _normalize_resource_changes(changes["resource_state_changes"])
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
            "hybrid" if provider_extraction or annotations else "deterministic_extractor"
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
        "canon_extraction_contract_version": "canon-semantic-extraction-v2",
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
) -> dict[str, Any]:
    if not all((project_id, revision_asset_version_id, context_bundle_version_id)):
        raise KernelError("CANON_INPUT_INVALID", "versioned canon lineage is required")
    if extraction is None:
        if revision is None:
            raise KernelError("CANON_EXTRACTION_REQUIRED", "Canon reduction requires extraction")
        extraction = extract_canon_candidates(
            project_id=project_id,
            revision=revision,
            revision_asset_version_id=revision_asset_version_id,
            context_bundle_version_id=context_bundle_version_id,
        )
    if extraction.get("project_id") != project_id:
        raise KernelError("CROSS_PROJECT_REFERENCE", "Canon extraction belongs to another project")
    chapter = int(extraction["chapter"])
    state = {key: list(values) for key, values in (historical_state or {}).items()}
    previous = [*existing_facts, *state.get("canon_snapshot", [])]
    facts = [_normalize_fact(item, chapter, revision_asset_version_id) for item in extraction.get("canon_assertion_candidates", [])]
    deterministic_validation = validate_deterministic_continuity(
        chapter=chapter,
        historical_state=state,
        extraction=extraction,
    )
    conflicts = _fact_conflicts(previous, facts)
    conflicts.extend(deterministic_validation["violations"])
    if extraction.get("approval_required_changes") and not extraction.get(
        "high_impact_approval", {}
    ).get("status") == "APPROVED":
        conflicts.append(
            _conflict(
                "HIGH_IMPACT_SEMANTIC_CHANGE_REQUIRES_APPROVAL",
                state,
                extraction.get("approval_required_changes"),
                "approve or reject each high-impact semantic change before reduction",
            )
        )
    return {
        "project_id": project_id,
        "chapter": chapter,
        "source_asset_version_id": revision_asset_version_id,
        "context_bundle_version_id": context_bundle_version_id,
        "facts": facts,
        "conflicts": conflicts,
        "deterministic_validation": deterministic_validation,
        "gate": "BLOCKED" if any(item["severity"] == "blocking" for item in conflicts) else "PASSED",
        "historical_input_version_ids": sorted(
            {
                str(item.get("asset_version_id"))
                for values in state.values() for item in values
                if item.get("asset_version_id")
            }
        ),
        "state_changes": _narrative_state_changes(extraction, facts),
        "rebuildable": True,
        "rollback_aware": True,
        "canon_contract_version": "canon-update-domain-v4",
    }


def _normalize_fact(item: dict[str, Any], chapter: int, source: str) -> dict[str, Any]:
    subject = str(item.get("subject") or "").strip()
    predicate = str(item.get("predicate") or "").strip()
    object_value = str(item.get("object") or "").strip()
    if not all((subject, predicate, object_value)):
        raise KernelError("CANON_ASSERTION_INVALID", "canon assertion requires subject/predicate/object")
    return {
        "subject": subject, "predicate": predicate, "object": object_value,
        "effective_from_chapter": int(item.get("effective_from_chapter") or chapter),
        "source_asset_version_id": source,
        "supersedes_event_id": str(item.get("supersedes_event_id") or ""),
        "extraction_evidence": dict(item.get("extraction_evidence") or {}),
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
            raise KernelError("CANON_ANNOTATION_INVALID", "operator annotation is not typed")
        target[field].append({**change, "extractor_type": "operator_annotation"})


def _normalize_resource_changes(changes: list[dict[str, Any]]) -> None:
    """Close the extraction/reducer boundary without weakening balance semantics."""

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
    approval_required = impact_type in HIGH_IMPACT_CHANGE_TYPES or confidence < 0.65
    return {
        **item,
        "confidence": confidence,
        "extractor_type": extractor,
        "source_revision_asset_version_id": revision_asset_version_id,
        "extraction_evidence": {
            "span": {"start": start, "end": end},
            "excerpt_digest": (
                "sha256:" + hashlib.sha256(excerpt.encode()).hexdigest() if excerpt else ""
            ),
            "source_revision_asset_version_id": revision_asset_version_id,
            "provider_id": str(item.get("provider_id") or ""),
            "model_id": str(item.get("model_id") or ""),
            "prompt_version": str(item.get("prompt_version") or ""),
            "previous_state_reference": str(
                item.get("previous_state_reference") or ""
            ),
        },
        "approval_requirement": "REQUIRED" if approval_required else "NONE",
    }


def _conflict(code: str, existing: Any, candidate: Any, recommendation: str, *, approval: bool = True) -> dict[str, Any]:
    return {
        "conflict_code": code,
        "severity": "blocking",
        "existing_version": existing,
        "candidate_version": candidate,
        "evidence": {"existing": existing, "candidate": candidate},
        "recommended_resolution": recommendation,
        "approval_requirement": "REQUIRED" if approval else "NONE",
    }


def _fact_conflicts(previous: list[dict[str, Any]], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts = []
    for fact in facts:
        for old in previous:
            if old.get("subject") == fact["subject"] and old.get("predicate") == fact["predicate"] and old.get("object") != fact["object"] and not fact["supersedes_event_id"]:
                conflicts.append(_conflict("FACT_CONTRADICTION", old, fact, "supersede explicitly or revise the chapter"))
    return conflicts


def validate_deterministic_continuity(
    *,
    chapter: int,
    historical_state: dict[str, list[dict[str, Any]]],
    extraction: dict[str, Any],
) -> dict[str, Any]:
    """Validate only invariants supported by explicit structured Authority data."""

    if chapter <= 0:
        raise ValueError("chapter must be positive")
    state = {
        kind: _state_items(values)
        for kind, values in historical_state.items()
    }
    conflicts: list[dict[str, Any]] = []
    _validate_transition_preconditions(
        conflicts,
        state=state,
        extraction=extraction,
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
            conflicts.append(_conflict("TEMPORAL_CONTRADICTION", state.get("timeline_snapshot", []), event, "place the event after the latest frozen timeline boundary"))
    for change in extraction.get("character_state_changes", []):
        existing = next((item for item in state.get("character_state", []) if item.get("character_id") == change.get("character_id")), None)
        if existing and existing.get("canonical_name") and change.get("canonical_name") and existing["canonical_name"] != change["canonical_name"]:
            conflicts.append(_conflict("CHARACTER_IDENTITY_CONTRADICTION", existing, change, "create an alias/merge proposal instead of changing identity"))
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
            known = {
                str(item)
                for item in existing.get("known_fact_ids", [])
            } | {
                str(item)
                for item in change.get("acquired_fact_ids", [])
            }
            required = {
                str(item) for item in change.get("requires_fact_ids", [])
            }
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
        source_id = str(change.get("source_id") or change.get("source_character_id") or "")
        target_id = str(change.get("target_id") or change.get("target_character_id") or "")
        if source_id and source_id == target_id and not change.get("allow_self_relation"):
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
            (existing or {}).get("status")
            or (existing or {}).get("trust_state")
            or ""
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
            conflicts.append(_conflict("RELATIONSHIP_CONTRADICTION", state.get("relationship_state", []), change, "add reconciliation evidence or preserve distrust"))
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
            conflicts.append(_conflict("WORLD_RULE_CONTRADICTION", state.get("world_rule", []), usage, "pay the rule exception cost"))
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
            conflicts.append(_conflict("POWER_PROGRESSION_CONTRADICTION", state.get("power_state", []), change, "supply training, equipment, condition, or cost evidence"))
    for change in extraction.get("foreshadow_changes", []):
        _validate_lifecycle_transition(
            conflicts,
            state=state.get("foreshadow_state", []),
            change=change,
            identity_key="thread_id",
            code="FORESHADOW_LIFECYCLE_CONTRADICTION",
        )
        if change.get("status") == "PAID" and not change.get("payoff_evidence"):
            conflicts.append(_conflict("FORESHADOW_LIFECYCLE_CONTRADICTION", state.get("foreshadow_state", []), change, "add causal payoff evidence"))
    for change in extraction.get("promise_changes", []):
        _validate_lifecycle_transition(
            conflicts,
            state=state.get("reader_promise", []),
            change=change,
            identity_key="promise_id",
            code="PROMISE_LIFECYCLE_CONTRADICTION",
        )
        if change.get("status") == "PAID" and not change.get("payoff_evidence"):
            conflicts.append(_conflict("PROMISE_LIFECYCLE_CONTRADICTION", state.get("reader_promise", []), change, "add reader-visible fulfillment evidence"))
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
            existing is not None
            and before is not None
            and float(before) != float(existing.get("balance", before))
        ) or (
            before is not None
            and delta is not None
            and after is not None
            and float(before) + float(delta) != float(after)
        ) or (
            after is not None
            and float(after) < 0
            and not change.get("allow_negative_balance")
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
        str(item.get("fact_id") or item.get("proposition_id") or "")
        for item in extraction.get("disclosure_events", [])
        if str(item.get("audience") or "").upper() in {"READER", "ALL"}
        and str(item.get("disclosure_mode") or "").upper() != "WITHHOLD"
    }
    for change in extraction.get("reader_knowledge_changes", []):
        fact_id = str(change.get("fact_id") or change.get("proposition_id") or "")
        if (
            str(change.get("status") or "").upper() != "UNKNOWN"
            and fact_id not in disclosures
        ):
            conflicts.append(
                _conflict(
                    "READER_KNOWLEDGE_WITHOUT_DISCLOSURE",
                    {"reader_knowledge": "not advanced by Truth alone"},
                    change,
                    "bind a supported reader-facing Disclosure event or omit the Reader Knowledge change",
                )
            )
    return {
        "gate": "BLOCKED" if conflicts else "PASSED",
        "violations": conflicts,
        "deterministic_rule_count": 12,
        "used_text_heuristics": False,
        "semantic_judgment_required": [
            "CHARACTER_MOTIVATION",
            "EMOTIONAL_PLAUSIBILITY",
            "OOC",
        ],
        "contract_version": "deterministic-continuity-v1",
    }


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
        "reader_knowledge_changes",
        ("reader_knowledge",),
        (("fact_id", "proposition_id"),),
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
    """Reject narrative CAS claims that are not backed by accepted state.

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
                    ("from_state", "state"),
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
    invalid = (
        bool(declared_from) and declared_from != existing_status
    ) or (
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
    """Expose Canon-approved deltas using the shared Narrative State vocabulary."""

    changes = {
        "canon_fact": facts,
        "character_state": extraction.get("character_state_changes", []),
        "relationship_state": extraction.get("relationship_changes", []),
        "timeline_event": extraction.get("timeline_event_candidates", []),
        "foreshadow_state": extraction.get("foreshadow_changes", []),
        "reader_promise": extraction.get("promise_changes", []),
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
    return {key: list(values) for key, values in changes.items() if values}


__all__ = [
    "build_canon_update",
    "extract_canon_candidates",
    "validate_deterministic_continuity",
    "CanonSemanticProviderPort",
]
