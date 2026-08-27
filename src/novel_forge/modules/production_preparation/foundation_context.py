"""Protected Chapter projections for authoritative Character and Reader contracts."""

from __future__ import annotations

import json
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError


_CHARACTER_SEMANTIC_FIELDS = (
    "role",
    "desire",
    "need",
    "fear",
    "wound",
    "false_belief",
    "values",
    "moral_boundary",
    "agency",
    "capability",
    "weakness",
    "voice",
    "secret",
    "relationship_function",
    "arc_direction",
)
_READER_PROMISE_FIELDS = (
    "objective",
    "genre",
    "target_reader",
    "emotional_contract",
    "ending_contract",
)


def project_character_foundation_context(
    *,
    asset_type: str,
    content: Mapping[str, Any],
    source_asset_version_id: str,
) -> dict[str, Any]:
    """Return a non-lossy, executable identity projection.

    Historical Character assets remain readable, but Chapter execution must not
    infer a name, alias, or pronoun from prose, a slug, or a model response.
    """

    if asset_type not in {"character_cast", "character_card"}:
        raise KernelError(
            "CHARACTER_FOUNDATION_TYPE_UNSUPPORTED",
            "protected Character projection requires CharacterCast or CharacterCard",
        )
    if not source_asset_version_id:
        raise KernelError(
            "CHARACTER_IDENTITY_LINEAGE_MISSING",
            "protected Character projection requires an exact AssetVersion",
        )
    payload = _semantic_payload(content)
    if asset_type == "character_cast":
        raw_characters = payload.get("characters") or payload.get("character_system")
        if not isinstance(raw_characters, list) or not raw_characters:
            raise KernelError(
                "CHARACTER_IDENTITY_CONTRACT_INCOMPLETE",
                "CharacterCast requires at least one executable identity",
            )
    else:
        raw_characters = [payload]

    facts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_aliases: dict[str, str] = {}
    for index, raw in enumerate(raw_characters):
        if not isinstance(raw, Mapping):
            raise KernelError(
                "CHARACTER_IDENTITY_CONTRACT_INCOMPLETE",
                f"Character identity {index} is not an object",
            )
        item = dict(raw)
        character_id = str(item.get("character_id") or item.get("entity_id") or "").strip()
        canonical_name = str(
            item.get("canonical_name") or item.get("name") or ""
        ).strip()
        raw_aliases = item.get("aliases") or []
        raw_pronouns = item.get("pronouns") or (
            [item["pronoun"]] if item.get("pronoun") else []
        )
        if (
            not character_id
            or not canonical_name
            or not isinstance(raw_aliases, list)
            or not isinstance(raw_pronouns, list)
        ):
            raise KernelError(
                "CHARACTER_IDENTITY_CONTRACT_INCOMPLETE",
                "Character identity requires character_id, canonical name, aliases, and pronouns",
            )
        aliases = _unique_strings([canonical_name, *raw_aliases])
        pronouns = _unique_strings(raw_pronouns)
        if not aliases or not pronouns or character_id in seen_ids:
            raise KernelError(
                "CHARACTER_IDENTITY_CONTRACT_INCOMPLETE",
                "Character identities require unique ids and non-empty aliases/pronouns",
            )
        for alias in aliases:
            owner = seen_aliases.get(alias)
            if owner is not None and owner != character_id:
                raise KernelError(
                    "CHARACTER_IDENTITY_ALIAS_AMBIGUOUS",
                    f"Character alias {alias!r} belongs to multiple identities",
                )
            seen_aliases[alias] = character_id
        seen_ids.add(character_id)
        stable = {
            field: item[field]
            for field in _CHARACTER_SEMANTIC_FIELDS
            if item.get(field) not in (None, "", [])
        }
        facts.append(
            {
                "kind": "character_identity_contract",
                "character_id": character_id,
                "canonical_name": canonical_name,
                "aliases": aliases,
                "pronouns": pronouns,
                "stable_characterization": stable,
                "source_asset_version_id": source_asset_version_id,
            }
        )

    names = ", ".join(str(item["canonical_name"]) for item in facts)
    return _protected_projection(
        safe_summary=f"Protected authoritative Character identities: {names}.",
        structured_facts=facts,
        narrative_function="critical_character_state",
    )


def project_reader_promise_context(
    *, content: Mapping[str, Any], source_asset_version_id: str
) -> dict[str, Any]:
    """Project exact Reader Promise semantics without promoting intent to truth."""

    if not source_asset_version_id:
        raise KernelError(
            "READER_PROMISE_LINEAGE_MISSING",
            "protected Reader Promise projection requires an exact AssetVersion",
        )
    payload = _semantic_payload(content)
    promise = str(
        payload.get("reader_promise")
        or payload.get("reading_promise")
        or payload.get("promise")
        or payload.get("contract")
        or ""
    ).strip()
    if not promise:
        raise KernelError(
            "READER_PROMISE_CONTRACT_INCOMPLETE",
            "ReaderPromise requires explicit reader-facing semantics",
        )
    semantic_fields = {
        field: payload[field]
        for field in _READER_PROMISE_FIELDS
        if payload.get(field) not in (None, "", [])
    }
    return _protected_projection(
        safe_summary="Protected Reader Promise contract; advisory intent, not Canon.",
        structured_facts=[
            {
                "kind": "reader_promise_contract",
                "promise": promise,
                **semantic_fields,
                "authority_semantics": "FUTURE_EDITORIAL_CONTRACT",
                "source_asset_version_id": source_asset_version_id,
            }
        ],
        narrative_function="reader_promise_contract",
    )


def _semantic_payload(content: Mapping[str, Any]) -> dict[str, Any]:
    candidate = content.get("candidate_payload")
    return dict(candidate) if isinstance(candidate, Mapping) else dict(content)


def _unique_strings(values: list[Any]) -> list[str]:
    return list(
        dict.fromkeys(
            normalized
            for item in values
            if (normalized := str(item or "").strip())
        )
    )


def _protected_projection(
    *,
    safe_summary: str,
    structured_facts: list[dict[str, Any]],
    narrative_function: str,
) -> dict[str, Any]:
    rendered = json.dumps(
        {"safe_summary": safe_summary, "structured_facts": structured_facts},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "safe_summary": safe_summary,
        "structured_facts": structured_facts,
        "narrative_function": narrative_function,
        "context_class": "PROTECTED",
        "compression_method": "authority_projection",
        "semantic_projection": True,
        "estimated_tokens": max(1, len(rendered) // 4),
    }


__all__ = [
    "project_character_foundation_context",
    "project_reader_promise_context",
]
