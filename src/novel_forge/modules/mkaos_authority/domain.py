from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from .applicability import USAGE_ROLES, assess_applicability, validate_applicability_contract


FORBIDDEN_SOURCE_KEYS = frozenset(
    {
        "raw",
        "raw_content",
        "raw_source",
        "raw_text",
        "clean_text",
        "source_content",
        "source_text",
        "original_sentence",
        "original_sentences",
        "excerpt",
        "excerpts",
        "quote",
        "quotes",
        "content_base64",
        "ready_made_plot",
        "source_event_sequence",
        "source_specific_event_sequence",
        "entity_replacement_template",
        "character_replacement_template",
        "plot_template",
    }
)

NARRATIVE_INTELLIGENCE_FAMILIES = frozenset(
    {
        "NARRATIVE_PRIMITIVE",
        "NARRATIVE_MECHANISM",
        "ARC_BEAT_PATTERN",
        "CONFLICT_ESCALATION_REVERSAL_PAYOFF",
        "CHARACTER_TRANSFORMATION",
        "RELATIONSHIP",
        "MYSTERY_CLUE_REVEAL",
        "WORLD_CONSEQUENCE",
        "FACTION_DYNAMICS",
        "POWER_RESOURCE_PROGRESSION",
        "READER_EMOTIONAL_CURVE",
        "THEME_MORAL_DILEMMA",
        "SCENE_INTERACTION",
        "ANTI_PATTERN_FAILURE",
        "PROFESSIONAL_CAUSAL_MECHANISM",
    }
)
NARRATIVE_INTELLIGENCE_KINDS = frozenset(
    {"NARRATIVE_INTELLIGENCE", "DOMAIN_INTELLIGENCE"}
)
NARRATIVE_INTELLIGENCE_SCOPES = frozenset({"STORY", "ARC", "CHAPTER", "SCENE"})
NARRATIVE_INTELLIGENCE_POLICY_VERSION = "knowledge-grounded-selection-v2"
BOOK_KNOWLEDGE_ACCESS_MODES = frozenset(
    {"PROJECT_DEFAULT", "ALLOW_ONLY", "DENY_ALL"}
)
BOOK_KNOWLEDGE_ACCESS_SCHEMA_VERSION = "book-knowledge-access-policy.v1"
BOOK_KNOWLEDGE_ACCESS_EXPERIMENTAL_SCHEMA_VERSION = (
    "book-knowledge-access-policy.v2"
)


@dataclass(frozen=True, slots=True)
class KnowledgeEvidenceSpan:
    source_chunk_asset_version_id: str
    chunk_byte_start: int
    chunk_byte_end: int
    evidence_hash: str

    def __post_init__(self) -> None:
        if not self.source_chunk_asset_version_id.strip():
            raise ValueError("source chunk AssetVersion identity is required")
        if self.chunk_byte_start < 0 or self.chunk_byte_end <= self.chunk_byte_start:
            raise ValueError("knowledge evidence span is invalid")
        _require_sha256(self.evidence_hash, "knowledge evidence Hash")


@dataclass(frozen=True, slots=True)
class KnowledgePackSelection:
    knowledge_card_asset_version_id: str
    usage_role: str
    frozen_weight: Decimal

    def __post_init__(self) -> None:
        if not self.knowledge_card_asset_version_id.strip():
            raise ValueError("KnowledgeCard AssetVersion identity is required")
        normalized_role = self.usage_role.strip().upper()
        if normalized_role not in {"PRINCIPLE", "CONSTRAINT", "CHECK", "REFERENCE"}:
            raise ValueError("KnowledgePack usage role is invalid")
        try:
            weight = Decimal(str(self.frozen_weight))
        except InvalidOperation as exc:
            raise ValueError("KnowledgePack weight is invalid") from exc
        if weight <= 0 or weight > 100:
            raise ValueError("KnowledgePack weight must be within (0, 100]")
        object.__setattr__(self, "usage_role", normalized_role)
        object.__setattr__(self, "frozen_weight", weight)


@dataclass(frozen=True, slots=True)
class NarrativeIntelligenceNeed:

    scope: str
    target_stage: str
    current_state_terms: tuple[str, ...] = ()
    desired_transformation_terms: tuple[str, ...] = ()
    genre_tags: tuple[str, ...] = ()
    conflict_tags: tuple[str, ...] = ()
    reader_effect_tags: tuple[str, ...] = ()
    theme_tags: tuple[str, ...] = ()
    hard_constraints: tuple[str, ...] = ()
    recently_used_repetition_keys: tuple[str, ...] = ()
    semantic_families: tuple[str, ...] = ()
    required_card_asset_version_ids: tuple[str, ...] = ()
    condition_sources: Mapping[str, Any] = dataclass_field(default_factory=dict)
    craft_context: Mapping[str, Any] = dataclass_field(default_factory=dict)
    craft_policy: Mapping[str, Any] = dataclass_field(default_factory=dict)
    recent_craft_usage: tuple[Mapping[str, Any], ...] = ()
    craft_selection_policy_version: str = "craft-need-driven-selection.v2"

    def __post_init__(self) -> None:
        from .craft_matching import require_selection_version
        require_selection_version(self.craft_selection_policy_version)
        scope = self.scope.strip().upper()
        if scope not in NARRATIVE_INTELLIGENCE_SCOPES:
            raise ValueError("Narrative Intelligence scope is invalid")
        if not self.target_stage.strip():
            raise ValueError("Narrative Intelligence target stage is required")
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "target_stage", self.target_stage.strip())
        for field in (
            "current_state_terms",
            "desired_transformation_terms",
            "genre_tags",
            "conflict_tags",
            "reader_effect_tags",
            "theme_tags",
            "hard_constraints",
            "recently_used_repetition_keys",
            "required_card_asset_version_ids",
        ):
            normalized = (
                tuple(sorted({str(item).strip() for item in self.hard_constraints if str(item).strip()}))
                if field == "hard_constraints"
                else _bounded_terms(getattr(self, field), field)
            )
            object.__setattr__(self, field, normalized)
        families = tuple(
            sorted({str(item).strip().upper() for item in self.semantic_families})
        )
        if len(families) > 15 or any(
            item not in NARRATIVE_INTELLIGENCE_FAMILIES for item in families
        ):
            raise ValueError("Narrative Intelligence semantic families are invalid")
        object.__setattr__(self, "semantic_families", families)

    @property
    def need_digest(self) -> str:
        return _canonical_hash(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            name: getattr(self, name) for name in self.__dataclass_fields__
            if name != "condition_sources"
        }
        if self.craft_selection_policy_version == "craft-context-affinity-selection.v1":
            payload.pop("craft_selection_policy_version")
        payload["condition_sources"] = {
            role: {key: source.get(key, "") for key in ("asset_version_id", "content_hash")}
            for role, source in self.condition_sources.items()
        }
        for key, value in tuple(payload.items()):
            if isinstance(value, tuple):
                payload[key] = list(value)
        if include_digest:
            payload["need_digest"] = self.need_digest
        return payload


def resolve_book_knowledge_access_policy(
    *,
    production_profile: Mapping[str, Any],
    project_id: str,
    book_id: str,
) -> dict[str, Any]:
    if not project_id.strip() or not book_id.strip():
        raise ValueError("Book Knowledge access requires project and Book identity")
    configured = production_profile.get("knowledge_access_policy")
    explicit = configured is not None
    if configured is None:
        value: dict[str, Any] = {}
    elif isinstance(configured, Mapping):
        value = dict(configured)
    else:
        raise KernelError(
            "BOOK_KNOWLEDGE_ACCESS_POLICY_INVALID",
            "production profile Knowledge access policy must be an object",
        )
    allowed_fields = {
        "policy_id",
        "policy_version",
        "mode",
        "allowed_knowledge_card_asset_version_ids",
        "usage_scope",
        "experimental_policy_version",
    }
    if set(value) - allowed_fields:
        raise KernelError(
            "BOOK_KNOWLEDGE_ACCESS_POLICY_INVALID",
            "Book Knowledge access policy contains unsupported fields",
        )
    mode = str(value.get("mode") or "PROJECT_DEFAULT").strip().upper()
    policy_id = str(
        value.get("policy_id") or "book-production-knowledge-access"
    ).strip()
    policy_version = value.get("policy_version", 1)
    raw_allowed = value.get("allowed_knowledge_card_asset_version_ids") or ()
    usage_scope = str(value.get("usage_scope") or "PRODUCTION").strip().upper()
    experimental_policy_version = str(
        value.get("experimental_policy_version") or ""
    ).strip()
    if (
        mode not in BOOK_KNOWLEDGE_ACCESS_MODES
        or not policy_id
        or len(policy_id) > 128
        or not isinstance(policy_version, int)
        or isinstance(policy_version, bool)
        or policy_version <= 0
        or not isinstance(raw_allowed, (list, tuple))
        or usage_scope not in {"PRODUCTION", "EXPERIMENTAL_VALIDATION"}
    ):
        raise KernelError(
            "BOOK_KNOWLEDGE_ACCESS_POLICY_INVALID",
            "Book Knowledge access policy has invalid identity, version, mode, or set",
        )
    allowed = tuple(str(item).strip() for item in raw_allowed)
    if (
        len(allowed) > 5_000
        or any(not item or len(item) > 500 for item in allowed)
        or len(set(allowed)) != len(allowed)
        or (mode == "ALLOW_ONLY" and not allowed)
        or (mode != "ALLOW_ONLY" and bool(allowed))
    ):
        raise KernelError(
            "BOOK_KNOWLEDGE_ACCESS_POLICY_INVALID",
            "ALLOW_ONLY requires a unique non-empty set; other modes require an empty set",
        )
    if (
        usage_scope == "EXPERIMENTAL_VALIDATION"
        and (
            not explicit
            or mode != "ALLOW_ONLY"
            or not experimental_policy_version
            or len(experimental_policy_version) > 128
        )
    ) or (usage_scope == "PRODUCTION" and experimental_policy_version):
        raise KernelError(
            "BOOK_KNOWLEDGE_ACCESS_POLICY_INVALID",
            "experimental Knowledge access requires an explicit allowlist and policy version",
        )
    body = {
        "schema_version": (
            BOOK_KNOWLEDGE_ACCESS_EXPERIMENTAL_SCHEMA_VERSION
            if usage_scope == "EXPERIMENTAL_VALIDATION"
            else BOOK_KNOWLEDGE_ACCESS_SCHEMA_VERSION
        ),
        "policy_id": policy_id,
        "policy_version": policy_version,
        "project_id": project_id,
        "book_id": book_id,
        "mode": mode,
        "allowed_knowledge_card_asset_version_ids": sorted(allowed),
        "configured_explicitly": explicit,
    }
    if usage_scope == "EXPERIMENTAL_VALIDATION":
        body.update(
            {
                "usage_scope": usage_scope,
                "experimental_policy_version": experimental_policy_version,
            }
        )
    return {**body, "policy_hash": _canonical_hash(body)}


def validate_book_knowledge_access_policy(
    policy: Mapping[str, Any], *, project_id: str, book_id: str
) -> dict[str, Any]:
    required = {
        "schema_version",
        "policy_id",
        "policy_version",
        "project_id",
        "book_id",
        "mode",
        "allowed_knowledge_card_asset_version_ids",
        "configured_explicitly",
        "policy_hash",
    }
    frozen = dict(policy)
    schema_version = frozen.get("schema_version")
    if schema_version == BOOK_KNOWLEDGE_ACCESS_EXPERIMENTAL_SCHEMA_VERSION:
        required.update({"usage_scope", "experimental_policy_version"})
    if (
        set(frozen) != required
        or schema_version
        not in {
            BOOK_KNOWLEDGE_ACCESS_SCHEMA_VERSION,
            BOOK_KNOWLEDGE_ACCESS_EXPERIMENTAL_SCHEMA_VERSION,
        }
        or frozen.get("project_id") != project_id
        or frozen.get("book_id") != book_id
        or not isinstance(frozen.get("configured_explicitly"), bool)
    ):
        raise KernelError(
            "BOOK_KNOWLEDGE_ACCESS_POLICY_DRIFT",
            "frozen Book Knowledge access policy has invalid scope or shape",
        )
    rebuilt = resolve_book_knowledge_access_policy(
        production_profile={
            "knowledge_access_policy": {
                "policy_id": frozen["policy_id"],
                "policy_version": frozen["policy_version"],
                "mode": frozen["mode"],
                "allowed_knowledge_card_asset_version_ids": frozen[
                    "allowed_knowledge_card_asset_version_ids"
                ],
                **(
                    {
                        "usage_scope": frozen["usage_scope"],
                        "experimental_policy_version": frozen[
                            "experimental_policy_version"
                        ],
                    }
                    if schema_version
                    == BOOK_KNOWLEDGE_ACCESS_EXPERIMENTAL_SCHEMA_VERSION
                    else {}
                ),
            }
        },
        project_id=project_id,
        book_id=book_id,
    )
    expected_body = {key: value for key, value in frozen.items() if key != "policy_hash"}
    if frozen["configured_explicitly"] is False:
        expected_body["configured_explicitly"] = False
    expected_hash = _canonical_hash(expected_body)
    if (
        rebuilt["mode"] != frozen["mode"]
        or rebuilt["allowed_knowledge_card_asset_version_ids"]
        != frozen["allowed_knowledge_card_asset_version_ids"]
        or frozen.get("policy_hash") != expected_hash
    ):
        raise KernelError(
            "BOOK_KNOWLEDGE_ACCESS_POLICY_DRIFT",
            "frozen Book Knowledge access policy identity has drifted",
        )
    return frozen


def validate_knowledge_candidate(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise KernelError("MKAOS_CANDIDATE_INVALID", "candidate must be an object")
    candidate = dict(payload)
    if "craft_mechanism" in candidate:
        from .craft import validate_craft_mechanism
        candidate["craft_mechanism"] = validate_craft_mechanism(candidate["craft_mechanism"])
    if "applicability_contract" in candidate:
        validate_applicability_contract(candidate["applicability_contract"])
    if "usage_role" in candidate and candidate["usage_role"] not in USAGE_ROLES:
        raise KernelError("MKAOS_CANDIDATE_INVALID", "knowledge usage_role is invalid")
    required_strings = (
        "concept_name",
        "discipline",
        "abstract_principle",
    )
    for field in required_strings:
        value = candidate.get(field)
        if not isinstance(value, str) or not value.strip():
            raise KernelError(
                "MKAOS_CANDIDATE_INVALID", f"candidate {field} is required"
            )
    for field in (
        "constraints",
        "conflict_generators",
        "review_checks",
        "copyright_boundaries",
    ):
        value = candidate.get(field)
        if not isinstance(value, list) or not value:
            raise KernelError(
                "MKAOS_CANDIDATE_INVALID", f"candidate {field} must be non-empty"
            )
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise KernelError(
                "MKAOS_CANDIDATE_INVALID", f"candidate {field} contains an invalid item"
            )
    structured_fields = {
        "knowledge_kind",
        "semantic_family",
        "mechanism",
        "applicability",
        "failure_conditions",
        "selection_tags",
        "repetition_key",
        "originality_boundary",
    }
    if structured_fields & set(candidate):
        missing = structured_fields - set(candidate)
        if missing:
            raise KernelError(
                "MKAOS_CANDIDATE_INVALID",
                "structured Narrative Intelligence fields must be complete",
            )
        _validate_structured_narrative_intelligence(candidate)
    _reject_forbidden_source_content(candidate)
    _validate_string_bounds(candidate)
    return candidate


def select_narrative_intelligence(
    need: NarrativeIntelligenceNeed,
    cards: tuple[Mapping[str, Any], ...],
    *,
    limit: int = 6,
) -> dict[str, Any]:

    if limit < 1 or limit > 12:
        raise ValueError("Narrative Intelligence selection limit must be within 1..12")
    from .craft_selection import craft_candidate_assessment, compose_craft_candidates, validate_craft_policy

    craft_policy = validate_craft_policy(need.craft_policy)
    recent = {item.casefold() for item in need.recently_used_repetition_keys}
    required_ids = set(need.required_card_asset_version_ids)
    if len(required_ids) > limit:
        raise KernelError("MKAOS_REQUIRED_KNOWLEDGE_SCOPE_TOO_LARGE", "required inherited mechanisms exceed this planning scope; split the scope before generation")
    requested_tags = {
        "genre": {item.casefold() for item in need.genre_tags},
        "conflict": {item.casefold() for item in need.conflict_tags},
        "reader_effect": {item.casefold() for item in need.reader_effect_tags},
        "theme": {item.casefold() for item in need.theme_tags},
    }
    requested_terms = _tokenize(
        (*need.current_state_terms, *need.desired_transformation_terms)
    )
    ranked: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_versions: set[str] = set()
    for card in cards:
        asset_version_id = str(card.get("asset_version_id") or "").strip()
        content_hash = str(card.get("content_hash") or "").strip()
        content = card.get("content")
        if (
            not asset_version_id
            or asset_version_id in seen_versions
            or not content_hash
            or not isinstance(content, Mapping)
        ):
            raise KernelError(
                "MKAOS_NARRATIVE_INTELLIGENCE_CARD_INVALID",
                "Narrative Intelligence selection requires immutable KnowledgeCard versions",
            )
        seen_versions.add(asset_version_id)
        assert_abstract_content_safe(content)
        abstract = content.get("abstract_content")
        if not isinstance(abstract, Mapping):
            raise KernelError(
                "MKAOS_NARRATIVE_INTELLIGENCE_CARD_INVALID",
                "KnowledgeCard does not expose governed abstract content",
            )
        lineage = content.get("lineage")
        if not isinstance(lineage, Mapping):
            lineage = {}
        normalized = _normalized_intelligence_content(abstract)
        assessment = assess_applicability(
            abstract, sources=need.condition_sources, hard_constraints=need.hard_constraints
        )
        if assessment["status"] == "REJECTED":
            rejected.append({
                "knowledge_card_asset_version_id": asset_version_id,
                "content_hash": content_hash,
                "reason": "KNOWLEDGE_APPLICABILITY_REJECTED",
                "applicability_assessment": assessment,
            })
            continue
        craft_assessment = None
        if normalized.get("craft_mechanism"):
            craft_assessment = craft_candidate_assessment(
                normalized["craft_mechanism"], context=need.craft_context,
                recent_usage=need.recent_craft_usage, policy=craft_policy,
                card_identity=(asset_version_id, content_hash),
                selection_policy_version=need.craft_selection_policy_version,
                applicability_status=assessment["status"],
            )
            if craft_assessment["rejection_reason"] not in {"", "CRAFT_NO_CONTEXT_MATCH"}:
                rejected.append({"knowledge_card_asset_version_id": asset_version_id, "content_hash": content_hash, "reason": craft_assessment["rejection_reason"], "applicability_assessment": assessment, "craft_assessment": craft_assessment})
                continue
            assessment = {**assessment, "status": "UNKNOWN" if assessment["status"] == "UNKNOWN" else "CONDITIONAL", "craft_applicability_judgment": "CONTEXTUAL_ADAPTATION_REQUIRED"}
        repetition_key = normalized["repetition_key"]
        if not craft_assessment and repetition_key.casefold() in recent and assessment["usage_role"] == "INSPIRATION" and asset_version_id not in required_ids:
            rejected.append(
                {
                    "knowledge_card_asset_version_id": asset_version_id,
                    "reason": "RECENT_REPETITION_RISK",
                    "applicability_assessment": assessment,
                }
            )
            continue
        score = 0
        reasons: list[str] = []
        if asset_version_id in required_ids:
            score += 1
            reasons.append("REQUIRED_BY_ACTIVE_PARENT_TRANSLATION")
        family = normalized["semantic_family"]
        explicit_family = "semantic_family" in abstract
        if not need.semantic_families:
            score += 1
            reasons.append("UNRESTRICTED_SEMANTIC_FAMILY")
        elif family in need.semantic_families:
            score += 8
            reasons.append(f"SEMANTIC_FAMILY:{family}")
        tags = normalized["selection_tags"]
        for tag_kind, requested in requested_tags.items():
            overlap = requested & {item.casefold() for item in tags[tag_kind]}
            if overlap:
                score += min(6, len(overlap) * 2)
                reasons.append(f"{tag_kind.upper()}:{','.join(sorted(overlap))}")
        overlap = requested_terms & _tokenize(
            (
                normalized["concept_name"],
                normalized["mechanism"],
                *normalized["applicability"],
                *normalized["conflict_generators"],
            )
        )
        if overlap:
            score += min(5, len(overlap))
            reasons.append(f"TERM_OVERLAP:{','.join(sorted(overlap)[:5])}")
        if craft_assessment is not None:
            score = craft_assessment["score"] + (1 if asset_version_id in required_ids else 0)
            reasons = list(craft_assessment["match_reasons"])
            if asset_version_id in required_ids and need.craft_selection_policy_version == "craft-need-driven-selection.v2":
                reasons.append("REQUIRED_BY_ACTIVE_PARENT_TRANSLATION")
            if need.craft_selection_policy_version == "craft-need-driven-selection.v2":
                craft_assessment["matching_assessment"].update(author_required_adjustment=int(asset_version_id in required_ids), selection_score=score)
                normalized["selection_tags"] = {**normalized["selection_tags"], "genre": [], "conflict": []}
        if score == 0 and not explicit_family and (craft_assessment is None or need.craft_selection_policy_version == "craft-context-affinity-selection.v1"):
            score = 1
            reasons.append("LEGACY_ABSTRACT_CARD_FALLBACK")
        if score == 0 and not (craft_assessment and craft_assessment["rejection_reason"] == "CRAFT_NO_CONTEXT_MATCH"):
            rejected.append(
                {
                    "knowledge_card_asset_version_id": asset_version_id,
                    "reason": "NO_STRUCTURED_MATCH",
                    "applicability_assessment": assessment,
                }
            )
            continue
        ranked.append(
            {
                "knowledge_card_asset_version_id": asset_version_id,
                "content_hash": content_hash,
                "knowledge_card_id": str(card.get("knowledge_card_id") or ""),
                "candidate_asset_version_id": str(
                    card.get("candidate_asset_version_id")
                    or lineage.get("candidate_asset_version_id")
                    or ""
                ),
                "governance_decision_asset_version_id": str(
                    card.get("governance_decision_asset_version_id")
                    or lineage.get("governance_decision_asset_version_id")
                    or ""
                ),
                "score": score,
                "match_reasons": reasons,
                "usage_role": assessment["usage_role"],
                "applicability_assessment": assessment,
                "selected_content": normalized,
                **({"craft_assessment": craft_assessment} if craft_assessment is not None else {}),
            }
        )
    unavailable = required_ids - {item["knowledge_card_asset_version_id"] for item in ranked}
    if unavailable:
        raise KernelError("MKAOS_REQUIRED_KNOWLEDGE_UNAVAILABLE", "inherited knowledge is revoked, excluded or conflicts with current inputs: " + ", ".join(sorted(unavailable)))
    ranked.sort(
        key=lambda item: (
            0 if item["knowledge_card_asset_version_id"] in required_ids else 1,
            {"APPLICABLE": 0, "CONDITIONAL": 1, "UNKNOWN": 2}[item["applicability_assessment"]["status"]],
            -int(item["score"]),
            str(item["knowledge_card_asset_version_id"]),
        )
    )
    selected, composition_rejected = compose_craft_candidates(
        ranked, limit=limit, required_ids=required_ids, policy=craft_policy,
        placement_scope=need.craft_context.get("reselection"),
    )
    if need.craft_context.get("reselection") and not any(item.get("selected_content", {}).get("craft_mechanism") for item in selected) and not craft_policy["reselection_policy"]["optional_abstention"]:
        raise KernelError("CRAFT_OPTIONAL_ABSTENTION_NOT_AUTHORIZED", "Concrete exclusions leave no Craft; the frozen policy requires an explicit author decision")
    rejected.extend(composition_rejected)
    result: dict[str, Any] = {
        "schema_version": "mkaos-narrative-intelligence-selection.v1",
        "policy_version": NARRATIVE_INTELLIGENCE_POLICY_VERSION,
        "need": need.to_dict(),
        **({"craft_selection_policy_version": need.craft_selection_policy_version,
            "craft_metadata_boundary": "Craft affinity, family and selection labels are descriptive metadata, not applicability predicates, author requirements or intended effects. Use only matched needs, resolved prerequisites and concrete adopted sites; do not impose metadata on this Book."}
            if need.craft_selection_policy_version == "craft-need-driven-selection.v2" else {}),
        **({"craft_policy": craft_policy} if any(item.get("content", {}).get("abstract_content", {}).get("craft_mechanism") for item in cards) else {}),
        "selected": selected,
        "rejected": sorted(
            rejected,
            key=lambda item: (
                item["knowledge_card_asset_version_id"],
                item["reason"],
            ),
        ),
        "selection_status": "SELECTED" if selected else "NO_ELIGIBLE_MATCH",
        "authority_boundary": {
            "semantic_role": "POSSIBILITY_ONLY",
            "may_mutate_story_authority": False,
            "may_mutate_narrative_state": False,
            "may_prove_accepted_reality": False,
            "planning_must_recompose_for_project": True,
        },
    }
    result["selection_digest"] = _canonical_hash(result)
    return result


def validate_evidence_spans(
    spans: tuple[KnowledgeEvidenceSpan, ...],
    *,
    source_chunk_sizes: Mapping[str, int],
) -> tuple[KnowledgeEvidenceSpan, ...]:
    if not spans or len(spans) > 1_000:
        raise KernelError(
            "MKAOS_EVIDENCE_INVALID", "candidate requires 1..1000 evidence spans"
        )
    ordered = tuple(
        sorted(
            spans,
            key=lambda item: (
                item.source_chunk_asset_version_id,
                item.chunk_byte_start,
                item.chunk_byte_end,
                item.evidence_hash,
            ),
        )
    )
    seen: set[tuple[str, int, int]] = set()
    for span in ordered:
        size = source_chunk_sizes.get(span.source_chunk_asset_version_id)
        if size is None:
            raise KernelError(
                "MKAOS_SOURCE_CHUNK_NOT_FOUND",
                "evidence references an unavailable SourceChunk AssetVersion",
            )
        identity = (
            span.source_chunk_asset_version_id,
            span.chunk_byte_start,
            span.chunk_byte_end,
        )
        if identity in seen:
            raise KernelError(
                "MKAOS_EVIDENCE_DUPLICATE", "duplicate evidence span is forbidden"
            )
        if span.chunk_byte_end > size:
            raise KernelError(
                "MKAOS_EVIDENCE_OUT_OF_BOUNDS",
                "evidence span exceeds the frozen SourceChunk byte size",
            )
        seen.add(identity)
    return ordered


def validate_pack_selections(
    selections: tuple[KnowledgePackSelection, ...],
) -> tuple[KnowledgePackSelection, ...]:
    if not selections or len(selections) > 500:
        raise KernelError(
            "MKAOS_PACK_SELECTION_INVALID", "KnowledgePack requires 1..500 items"
        )
    identities = [item.knowledge_card_asset_version_id for item in selections]
    if len(set(identities)) != len(identities):
        raise KernelError(
            "MKAOS_PACK_SELECTION_DUPLICATE",
            "KnowledgePack cannot contain the same KnowledgeCard version twice",
        )
    return tuple(
        sorted(
            selections,
            key=lambda item: (
                item.usage_role,
                item.knowledge_card_asset_version_id,
                str(item.frozen_weight),
            ),
        )
    )


def assert_abstract_content_safe(payload: Mapping[str, Any]) -> None:
    _reject_forbidden_source_content(payload)
    _validate_string_bounds(payload)


def assert_narrative_method_activation_safe(candidate: Mapping[str, Any]) -> None:
    if candidate.get("knowledge_kind") != "NARRATIVE_INTELLIGENCE":
        return
    operational_binding = re.compile(r"\b(?:project_id|book_id|target_scope_id|input_observation_asset_version_id|observation_hash|evidence_manifest_hash|abstraction_policy_version|processing_id)\s*[:=]")
    def check(value: Any, path: str) -> None:
        if isinstance(value, str) and operational_binding.search(value):
            raise KernelError("MKAOS_NARRATIVE_METHOD_OPERATIONAL_LEAK", f"Narrative method field {path} contains operational binding text; retain it in research lineage instead")
        if isinstance(value, Mapping):
            for key, item in value.items():
                check(item, f"{path}.{key}")
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                check(item, f"{path}[{index}]")
    for field in ("concept_name", "abstract_principle", "mechanism", "applicability", "failure_conditions", "constraints", "conflict_generators", "review_checks", "preconditions", "exceptions", "misuse_risks"):
        check(candidate.get(field), field)


def project_narrative_method_lineage(candidate: Mapping[str, Any]) -> tuple[dict, dict]:
    from copy import deepcopy

    original = deepcopy(dict(candidate))
    if (original.get("knowledge_kind") != "NARRATIVE_INTELLIGENCE"
            or original.get("semantic_family") != "NARRATIVE_MECHANISM"
            or original.get("craft_mechanism", {}).get("provenance", {}).get("origin") != "SOURCE_ABSTRACTION"):
        raise KernelError("MKAOS_METHOD_PROJECTION_SCOPE_INVALID", "Project only Source-derived narrative method metadata")
    projected = deepcopy(original)
    removed = []
    kept = []
    for index, value in enumerate(original.get("constraints") or ()):
        try:
            assert_narrative_method_activation_safe({"knowledge_kind": "NARRATIVE_INTELLIGENCE", "constraints": [value]})
        except KernelError as error:
            if error.code != "MKAOS_NARRATIVE_METHOD_OPERATIONAL_LEAK":
                raise
            identifier = r"[A-Za-z0-9:_-]+"
            administrative = (r"Project binding: (?:(?:project_id|book_id|scope_kind|scope_id)=" + identifier + r";?\s*)+\.?",
                r"This object is an unapproved Knowledge Candidate for project_id[ =]" + identifier
                + r", book_id[ =]" + identifier + r" and observation scope " + identifier
                + r"\. It grants no downstream adoption or active plan change\.")
            if not any(re.fullmatch(pattern, value) for pattern in administrative):
                raise
            removed.append({"field": "constraints", "index": index, "value": value})
        else:
            kept.append(value)
    projected["constraints"] = kept
    validate_knowledge_candidate(projected)
    assert_narrative_method_activation_safe(projected)
    return projected, {"contract_version": "narrative-method-lineage-projection.v1",
        "candidate_payload_hash": _canonical_hash(original), "abstract_content_hash": _canonical_hash(projected),
        "research_only_statements": removed, "non_constraints_fields_unchanged": True,
        "original_candidate_preserved": True, "evidence_ceiling": "METADATA_PROJECTION_NOT_EFFECT_VALIDATION"}


def _validate_structured_narrative_intelligence(candidate: Mapping[str, Any]) -> None:
    if str(candidate.get("knowledge_kind") or "").strip().upper() not in (
        NARRATIVE_INTELLIGENCE_KINDS
    ):
        raise KernelError("MKAOS_CANDIDATE_INVALID", "knowledge_kind is invalid")
    if str(candidate.get("semantic_family") or "").strip().upper() not in (
        NARRATIVE_INTELLIGENCE_FAMILIES
    ):
        raise KernelError("MKAOS_CANDIDATE_INVALID", "semantic_family is invalid")
    for field in ("mechanism", "repetition_key"):
        value = candidate.get(field)
        if not isinstance(value, str) or not value.strip():
            raise KernelError("MKAOS_CANDIDATE_INVALID", f"{field} is required")
    for field in ("applicability", "failure_conditions"):
        value = candidate.get(field)
        if (
            not isinstance(value, list)
            or not value
            or any(not isinstance(item, str) or not item.strip() for item in value)
        ):
            raise KernelError(
                "MKAOS_CANDIDATE_INVALID", f"{field} must be a non-empty string list"
            )
    tags = candidate.get("selection_tags")
    if not isinstance(tags, Mapping) or set(tags) != {
        "genre",
        "conflict",
        "reader_effect",
        "theme",
    }:
        raise KernelError(
            "MKAOS_CANDIDATE_INVALID", "selection_tags has an invalid shape"
        )
    for value in tags.values():
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise KernelError(
                "MKAOS_CANDIDATE_INVALID", "selection_tags values must be string lists"
            )
    boundary = candidate.get("originality_boundary")
    if (
        not isinstance(boundary, Mapping)
        or set(boundary)
        != {
            "source_specific_sequence_reusable",
            "named_entity_substitution_allowed",
            "expression_reuse_allowed",
        }
        or any(value is not False for value in boundary.values())
    ):
        raise KernelError(
            "MKAOS_ORIGINALITY_BOUNDARY_INVALID",
            "Narrative Intelligence must forbid source sequence, entity substitution, and expression reuse",
        )


def _normalized_intelligence_content(abstract: Mapping[str, Any]) -> dict[str, Any]:
    concept_name = str(abstract.get("concept_name") or "").strip()
    principle = str(abstract.get("abstract_principle") or "").strip()
    if not concept_name or not principle:
        raise KernelError(
            "MKAOS_NARRATIVE_INTELLIGENCE_CARD_INVALID",
            "KnowledgeCard lacks its abstract mechanism",
        )
    explicit_family = str(abstract.get("semantic_family") or "").strip().upper()
    family = explicit_family or (
        "PROFESSIONAL_CAUSAL_MECHANISM"
        if str(abstract.get("discipline") or "").strip().casefold()
        not in {"narrative_design", "fiction", "storytelling"}
        else "NARRATIVE_MECHANISM"
    )
    if family not in NARRATIVE_INTELLIGENCE_FAMILIES:
        raise KernelError(
            "MKAOS_NARRATIVE_INTELLIGENCE_CARD_INVALID",
            "KnowledgeCard semantic family is unsupported",
        )
    raw_tags = abstract.get("selection_tags")
    tags = dict(raw_tags) if isinstance(raw_tags, Mapping) else {}
    normalized_tags = {
        key: sorted(
            {str(item).strip() for item in tags.get(key) or () if str(item).strip()}
        )
        for key in ("genre", "conflict", "reader_effect", "theme")
    }
    repetition_key = str(abstract.get("repetition_key") or "").strip()
    if not repetition_key:
        repetition_key = (
            re.sub(r"[^a-z0-9]+", "-", concept_name.casefold()).strip("-")
            or _canonical_hash({"concept_name": concept_name})[-16:]
        )
    return {
        "knowledge_kind": str(
            abstract.get("knowledge_kind") or "NARRATIVE_INTELLIGENCE"
        )
        .strip()
        .upper(),
        "semantic_family": family,
        "concept_name": concept_name,
        "mechanism": str(abstract.get("mechanism") or principle).strip(),
        "applicability": _string_list(
            abstract.get("applicability"), fallback=abstract.get("constraints")
        ),
        "failure_conditions": _string_list(
            abstract.get("failure_conditions"),
            fallback=abstract.get("review_checks"),
        ),
        "constraints": _string_list(abstract.get("constraints")),
        "conflict_generators": _string_list(abstract.get("conflict_generators")),
        "review_checks": _string_list(abstract.get("review_checks")),
        "copyright_boundaries": _string_list(abstract.get("copyright_boundaries")),
        "selection_tags": normalized_tags,
        "repetition_key": repetition_key,
        **{
            key: abstract[key]
            for key in (
                "applicability_contract", "preconditions", "exceptions", "misuse_risks",
                "epistemic_status", "evidence_class", "verification_basis", "usage_role",
                "source_finding_codes", "craft_mechanism",
            )
            if key in abstract
        },
    }


def _string_list(value: Any, *, fallback: Any = None) -> list[str]:
    source = value if isinstance(value, list) and value else fallback
    return [str(item).strip() for item in source or () if str(item).strip()]


def _bounded_terms(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    normalized = tuple(
        sorted({str(item).strip() for item in values if str(item).strip()})
    )
    if len(normalized) > 32 or any(len(item) > 500 for item in normalized):
        raise ValueError(f"Narrative Intelligence {field} exceeds its bound")
    return normalized


def _tokenize(values: tuple[str, ...]) -> set[str]:
    return {
        token
        for value in values
        for token in re.findall(r"[\w\u4e00-\u9fff]+", value.casefold())
        if len(token) > 1
    }


def _canonical_hash(value: Mapping[str, Any]) -> str:
    serialized = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(serialized).hexdigest()


def _reject_forbidden_source_content(value: Any, *, path: str = "candidate") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in FORBIDDEN_SOURCE_KEYS:
                raise KernelError(
                    "MKAOS_SOURCE_LEAKAGE_BLOCKED",
                    f"forbidden source-expression field at {path}.{normalized}",
                )
            _reject_forbidden_source_content(item, path=f"{path}.{normalized}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_forbidden_source_content(item, path=f"{path}[{index}]")


def _validate_string_bounds(value: Any, *, path: str = "candidate") -> None:
    if isinstance(value, str):
        if len(value) > 2_000:
            raise KernelError(
                "MKAOS_ABSTRACTION_BOUNDARY_INVALID",
                f"abstract candidate string is too long at {path}",
            )
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _validate_string_bounds(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_string_bounds(item, path=f"{path}[{index}]")


def _require_sha256(value: str, label: str) -> None:
    digest = value.removeprefix("sha256:")
    if (
        not value.startswith("sha256:")
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError(f"{label} must be canonical sha256")


__all__ = [
    "BOOK_KNOWLEDGE_ACCESS_MODES",
    "BOOK_KNOWLEDGE_ACCESS_SCHEMA_VERSION",
    "KnowledgeEvidenceSpan",
    "KnowledgePackSelection",
    "NARRATIVE_INTELLIGENCE_FAMILIES",
    "NARRATIVE_INTELLIGENCE_POLICY_VERSION",
    "NarrativeIntelligenceNeed",
    "assert_abstract_content_safe",
    "resolve_book_knowledge_access_policy",
    "select_narrative_intelligence",
    "validate_evidence_spans",
    "validate_book_knowledge_access_policy",
    "validate_knowledge_candidate",
    "validate_pack_selections",
]
