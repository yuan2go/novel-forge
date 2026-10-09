from copy import deepcopy

from novel_forge.modules.chapter_authority.provider_output_contracts import _validate
import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning.epistemic_validation import (
    bind_planned_knowledge_schema,
    validate_planned_character_knowledge,
)


def schema():
    return {
        "type": "object",
        "properties": {
            "character_participation": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "character_id": {"type": "string"},
                        "known_fact_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
            }
        },
    }


def participation(facts, character="character:a"):
    return {
        "character_participation": [
            {"character_id": character, "known_fact_ids": facts}
        ]
    }


def knowledge(status="KNOWN", character="character:a"):
    return {
        "current_state": {
            "character_knowledge": [
                {
                    "state": {
                        "status": status,
                        "character_id": character,
                        "fact_id": "fact:observed",
                    }
                }
            ]
        }
    }


def test_unaccepted_working_experience_cannot_be_invented_as_entry_knowledge():
    state = {
        "current_state": {},
        "working_observations": [{"fact_id": "fact:observed"}],
    }
    bound = bind_planned_knowledge_schema(schema(), state)
    _validate(bound, participation([]), path="$")
    validate_planned_character_knowledge(participation([]), state)
    with pytest.raises(ValueError):
        _validate(bound, participation(["fact:observed"]), path="$")
    with pytest.raises(KernelError, match="SCENE_ACCEPTED_KNOWLEDGE_MISMATCH"):
        validate_planned_character_knowledge(participation(["fact:observed"]), state)


@pytest.mark.parametrize("status", ["BELIEVED", "SUSPECTED", "UNKNOWN"])
def test_schema_and_validator_exclude_unaccepted_epistemic_states(status):
    state = knowledge(status)
    with pytest.raises(ValueError):
        _validate(
            bind_planned_knowledge_schema(schema(), state),
            participation(["fact:observed"]),
            path="$",
        )
    with pytest.raises(KernelError, match="SCENE_ACCEPTED_KNOWLEDGE_MISMATCH"):
        validate_planned_character_knowledge(participation(["fact:observed"]), state)


def test_exact_frozen_accepted_fact_survives_and_foreign_fact_does_not():
    state = knowledge()
    original = schema()
    frozen = deepcopy(original)
    bound = bind_planned_knowledge_schema(original, state)
    _validate(bound, participation(["fact:observed"]), path="$")
    validate_planned_character_knowledge(participation(["fact:observed"]), state)
    with pytest.raises(ValueError):
        _validate(bound, participation(["fact:another-book"]), path="$")
    assert original == frozen


def test_accepted_fact_still_requires_correct_character_owner():
    state = knowledge()
    with pytest.raises(KernelError, match="SCENE_ACCEPTED_KNOWLEDGE_MISMATCH"):
        validate_planned_character_knowledge(
            participation(["fact:observed"], "character:b"), state
        )
