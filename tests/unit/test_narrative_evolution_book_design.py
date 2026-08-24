from __future__ import annotations

import pytest

from novel_forge.modules.book_design_authority import (
    BookDesignPayload,
    EVOLUTION_BOOK_DESIGN_SCHEMA_VERSION,
)
from novel_forge.modules.command_kernel.errors import KernelError


def _design() -> dict[str, object]:
    return {
        "schema_version": EVOLUTION_BOOK_DESIGN_SCHEMA_VERSION,
        "title": "The Glass Harbor",
        "genre": "speculative mystery",
        "premise": "A cartographer proves the city edits its maps.",
        "theme": "collective truth",
        "core_conflict": "Witnesses challenge a self-editing archive.",
        "reader_promise": "Every discovery forces a costly public choice.",
        "ending": "The archive becomes publicly accountable.",
        "protagonist": {
            "name": "Mara",
            "external_goal": "Restore the missing district.",
            "internal_need": "Trust collaborators.",
            "flaw": "Treats uncertainty as failure.",
            "arc": "Solitary certainty becomes accountable collaboration.",
        },
        "world_rules": ["Witnessed places resist erasure."],
        "target_chapters": 90,
        "core_characters": [
            {
                "character_id": "mara",
                "role": "protagonist",
                "long_term_goal": "Restore the district.",
                "causal_arc": "Isolation becomes collaboration.",
                "conflict_function": "Certainty delays collective action.",
            }
        ],
        "opposition_forces": [
            {
                "force_id": "archive",
                "goal": "Control memory.",
                "leverage": "Rewrite maps.",
                "escalation_pattern": "Denial becomes erasure.",
                "limit": "Witnesses delay erasure.",
            }
        ],
        "narrative_dna": {
            "core_question": "Who owns truth?",
            "recurring_choice": "Certainty or disclosure.",
            "cost_logic": "Every fact exposes a witness.",
            "distinctive_mechanism": "Maps change physical access.",
            "emotional_contract": "Discovery brings hope and public cost.",
        },
        "creative_foundation": {
            "target_reader": "mystery readers who value consequential choices",
            "why_worth_writing": "public truth has a personal cost",
            "subgenre": "institutional speculative mystery",
            "core_desire": "recover erased belonging",
            "core_fear": "certainty will isolate Mara",
            "narrative_engine": "each map anomaly forces disclosure or concealment",
            "differentiation": "geography changes through accountable archival choices",
            "emotional_contract": "wonder converts into shared responsibility",
            "serialization_potential": "nested districts reveal distinct institutional bargains",
            "thematic_question": "Can truth remain humane when it becomes public?",
            "ending_direction": "collective custody replaces solitary control",
        },
        "world_system": [
            {
                "rule_id": "witness-delay",
                "rule": "Witnessed places resist erasure.",
                "cost": "The witness becomes publicly exposed.",
                "exception": "A witness may recant.",
                "consequence": "Access remains open for seven days.",
                "conflict_potential": "The archive pressures witnesses to recant.",
                "narrative_function": "Turns knowledge into costly agency.",
            }
        ],
        "character_system": [
            {
                "character_id": "mara",
                "name": "Mara",
                "role": "protagonist",
                "desire": "restore the district",
                "need": "share uncertain evidence",
                "fear": "causing another erasure",
                "wound": "a failed solitary proof",
                "false_belief": "only certainty protects people",
                "values": "truth and care",
                "moral_boundary": "never fabricate a witness",
                "agency": "chooses what to disclose",
                "capability": "reads archival topology",
                "weakness": "withholds uncertainty",
                "voice": "precise until emotionally cornered",
                "secret": "her first map caused harm",
                "relationship_function": "must learn accountable trust",
                "arc_direction": "certainty becomes collective responsibility",
            }
        ],
    }


def test_evolution_foundation_is_strict_and_round_trips() -> None:
    design = BookDesignPayload.from_mapping(_design())

    assert design.schema_version == EVOLUTION_BOOK_DESIGN_SCHEMA_VERSION
    assert design.world_system[0]["cost"]
    assert design.character_system[0]["false_belief"]
    assert design.to_dict() == _design()


def test_evolution_world_rules_require_narrative_consequence() -> None:
    payload = _design()
    del payload["world_system"][0]["consequence"]  # type: ignore[index]

    with pytest.raises(KernelError, match="BOOK_DESIGN_INVALID"):
        BookDesignPayload.from_mapping(payload)
