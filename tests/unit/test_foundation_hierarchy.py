from __future__ import annotations

import pytest

from novel_forge.modules.book_design_authority import (
    FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
    BookDesignPayload,
    FoundationBinding,
    FoundationRole,
    QualifiedFoundationSet,
    foundation_upstream_digest,
)
from novel_forge.modules.command_kernel.errors import KernelError


def _hash(seed: str) -> str:
    return "sha256:" + (seed * 64)[:64]


def _binding(
    role: FoundationRole,
    *,
    upstream_digest: str = "",
) -> FoundationBinding:
    return FoundationBinding(
        role=role,
        authority="STORY_DESIGN_AUTHORITY",
        asset_version_id=f"asset-version:{role.value.lower()}",
        content_hash=_hash(role.value[0].lower()),
        schema_version=f"{role.value.lower().replace('_', '-')}.v1",
        qualification_evidence_asset_version_id=(f"qualification:{role.value.lower()}"),
        qualification_hash=_hash(role.value[-1].lower()),
        activation_id=f"activation:{role.value.lower()}",
        upstream_digest=upstream_digest,
    )


def _foundation_set() -> QualifiedFoundationSet:
    bindings: dict[FoundationRole, FoundationBinding] = {}
    for role in FoundationRole:
        parents = tuple(bindings[parent] for parent in role.required_parents)
        bindings[role] = _binding(
            role,
            upstream_digest=(foundation_upstream_digest(parents) if parents else ""),
        )
    return QualifiedFoundationSet.from_bindings(tuple(bindings.values()))


def test_foundation_set_requires_complete_exact_layer_lineage() -> None:
    foundation = _foundation_set()

    assert set(foundation.by_role) == set(FoundationRole)
    assert foundation.set_digest.startswith("sha256:")
    assert FoundationRole.CHARACTER_CAST.required_parents == (
        FoundationRole.CREATIVE_FOUNDATION,
        FoundationRole.THEME_CONTRACT,
        FoundationRole.ENDING_INTENT,
        FoundationRole.READER_PROMISE,
        FoundationRole.WORLD_BIBLE,
    )


def test_foundation_set_rejects_missing_duplicate_and_mixed_lineage() -> None:
    complete = _foundation_set()
    values = list(complete.bindings)

    with pytest.raises(KernelError, match="FOUNDATION_SET_INCOMPLETE"):
        QualifiedFoundationSet.from_bindings(tuple(values[:-1]))

    with pytest.raises(KernelError, match="FOUNDATION_BINDING_DUPLICATE"):
        QualifiedFoundationSet.from_bindings(tuple(values + [values[0]]))

    character = complete.by_role[FoundationRole.CHARACTER_CAST]
    drifted = FoundationBinding(
        role=character.role,
        authority=character.authority,
        asset_version_id=character.asset_version_id,
        content_hash=character.content_hash,
        schema_version=character.schema_version,
        qualification_evidence_asset_version_id=(
            character.qualification_evidence_asset_version_id
        ),
        qualification_hash=character.qualification_hash,
        activation_id=character.activation_id,
        upstream_digest=_hash("z"),
    )
    with pytest.raises(KernelError, match="FOUNDATION_LINEAGE_DRIFT"):
        QualifiedFoundationSet.from_bindings(
            tuple(drifted if item.role is drifted.role else item for item in values)
        )


def test_book_design_v5_is_reference_only_and_hash_stable() -> None:
    foundation = _foundation_set()
    payload = {
        "schema_version": FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
        "title": "The Glass Harbor",
        "target_chapters": 90,
        "foundation_set": foundation.to_dict(),
        "book_invariants": [
            "Accepted truth changes only through Chapter acceptance.",
            "Each recovered district exposes a cost-bearing witness.",
        ],
        "cross_layer_synthesis": [
            {
                "synthesis_id": "witness-choice",
                "source_roles": [
                    "CREATIVE_FOUNDATION",
                    "THEME_CONTRACT",
                    "WORLD_BIBLE",
                    "CHARACTER_CAST",
                ],
                "narrative_function": "Convert discovery into accountable agency.",
                "constraint": "No discovery resolves without a character choice.",
                "downstream_scope": "BOOK",
            }
        ],
        "narrative_dna": {
            "core_question": "Who owns truth?",
            "recurring_choice": "Certainty or accountable disclosure.",
            "cost_logic": "Every fact exposes a witness.",
            "distinctive_mechanism": "Maps change physical access.",
            "emotional_contract": "Discovery brings hope and public cost.",
        },
    }

    parsed = BookDesignPayload.from_mapping(payload)

    assert parsed.to_dict() == payload
    assert parsed.foundation_set == foundation
    assert parsed.world_rules == ()
    assert parsed.character_system == ()
    assert (
        parsed.content_hash
        == BookDesignPayload.from_mapping(
            dict(reversed(list(payload.items())))
        ).content_hash
    )


def test_book_design_v5_rejects_copied_foundation_truth() -> None:
    foundation = _foundation_set()
    payload = {
        "schema_version": FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
        "title": "The Glass Harbor",
        "target_chapters": 90,
        "foundation_set": foundation.to_dict(),
        "book_invariants": ["Truth remains accepted-evidence governed."],
        "cross_layer_synthesis": [
            {
                "synthesis_id": "causal-engine",
                "source_roles": ["WORLD_BIBLE", "CHARACTER_CAST"],
                "narrative_function": "Turn rules into costly choices.",
                "constraint": "Every rule use changes future options.",
                "downstream_scope": "BOOK",
            }
        ],
        "narrative_dna": {
            "core_question": "Who owns truth?",
            "recurring_choice": "Certainty or disclosure.",
            "cost_logic": "Every fact exposes a witness.",
            "distinctive_mechanism": "Maps change physical access.",
            "emotional_contract": "Discovery brings hope and cost.",
        },
        "world_system": [{"rule": "copied truth"}],
    }

    with pytest.raises(KernelError, match="BOOK_DESIGN_INVALID"):
        BookDesignPayload.from_mapping(payload)
