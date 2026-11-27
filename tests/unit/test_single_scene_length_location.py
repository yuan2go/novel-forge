import pytest

from novel_forge.modules.chapter_authority.domain_handlers import build_publish_gate
from novel_forge.modules.chapter_quality_authority.creative_validation import apply_work_constraint_actions
from novel_forge.modules.command_kernel.errors import KernelError


def repaired(text, *, current):
    assert callable(build_publish_gate)
    return apply_work_constraint_actions({"required_actions": [], "evidence_reports": [], "decision_chain": {}},
        admission={"blocked_dimensions": ["chapter_length"], "work_constraints": [{"dimension": "chapter_length",
            "status": "FAILED", "source_policy": "frozen-policy"}]},
        revision={"text": text, "scene_artifacts": [{"text": text}]}, target="exact-candidate", canon={},
        bounded_single_scene=current)


def test_current_single_scene_length_localization_preserves_outside_text_and_history():
    text = "She opened the door. She read the letter."
    old = repaired(text, current=False)["evidence_reports"][0]["evidence_locations"][0]
    assert old == {"start": 0, "end": len(text), "quote": text}
    current = repaired(text, current=True)["evidence_reports"][0]["evidence_locations"][0]
    assert 0 < current["end"] - current["start"] < len(text)
    assert text[current["start"]:current["end"]] == current["quote"]


def test_current_single_scene_without_bounded_boundary_fails_closed():
    with pytest.raises(KernelError, match="QUALITY_REVISION_LOCATION_REQUIRED"):
        repaired("One uninterrupted clause", current=True)
    assert repaired("One uninterrupted clause", current=False)["required_actions"]
