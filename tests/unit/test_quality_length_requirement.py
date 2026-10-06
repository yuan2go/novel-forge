import pytest

from novel_forge.modules.chapter_authority.quality_length_requirement import (
    freeze_requirement,
    require_length,
)
from novel_forge.modules.chapter_authority.current_quote_recovery import (
    failed_quote_feedback,
)
from novel_forge.modules.command_kernel.errors import KernelError


def context():
    return {
        "context_segments": [
            {
                "asset_type": "platform_profile",
                "asset_version_id": "profile-v1",
                "content_digest": "profile-hash",
                "summary": "platform",
                "structured_facts": [
                    {
                        "key": "chapter_length_rules",
                        "value": {
                            "unit": "HAN_CHARACTERS_V1",
                            "minimum": 5,
                            "maximum": 8,
                        },
                    }
                ],
            }
        ]
    }


def test_quality_edit_must_preserve_the_actual_frozen_han_bounds():
    requirement = freeze_requirement(context(), context_id="context-v1")
    assert requirement["minimum"] == 5 and requirement["maximum"] == 8
    assert requirement["context_asset_version_id"] == "context-v1"
    require_length(requirement, "甲乙丙丁戊。")
    for text in ("甲乙丙丁abcdefghij。", "甲乙丙丁戊己庚辛壬。"):
        with pytest.raises(KernelError, match="CHAPTER_LENGTH_REPAIR_INCOMPLETE"):
            require_length(requirement, text)
    duplicate = context()
    duplicate["context_segments"] *= 2
    with pytest.raises(KernelError, match="CHAPTER_LENGTH_SCOPE_PROFILE_CONFLICT"):
        freeze_requirement(duplicate, context_id="context-v1")


def test_quote_repair_keeps_literal_failure_and_full_original_result_hash():
    original = {
        "disclosure_events": [{"evidence_quote": "他核了一遍", "subject": "hero"}],
        "world_state_changes": [{"evidence_quote": "他看见署名"}],
    }
    feedback = failed_quote_feedback(
        original,
        "他看见署名。",
        target="candidate-v1",
        evidence={"source_effect_id": "real-receipt"},
    )
    assert feedback["failed_quotes_by_field"] == {
        "disclosure_events": [
            {
                "path": "$.disclosure_events[0].evidence_quote",
                "provider_quote": "他核了一遍",
                "literal_check": "FAILED",
            }
        ]
    }
    assert feedback["semantic_support"] == "NOT_RUN" and feedback[
        "full_rejected_output_hash"
    ].startswith("sha256:")
    assert original["disclosure_events"][0]["evidence_quote"] == "他核了一遍"
