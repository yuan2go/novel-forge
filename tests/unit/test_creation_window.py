import pytest
from novel_forge.modules.book_authority.creation_window import (
    validate_execution_window,
    execution_stop_chapter,
)


def test_window_bounds_delivery_and_preserves_full_book_default():
    assert execution_stop_chapter({}, target_chapters=240) == 240
    window = {"version": "creation-execution-window.v1", "stop_after_chapter": 3}
    policy = {
        "creation_input_policy": {
            "profiles": {
                "production_profile": {"content": {"execution_window": window}}
            }
        }
    }
    assert execution_stop_chapter(policy, target_chapters=240) == 3
    assert window["stop_after_chapter"] == 3


@pytest.mark.parametrize("stop", [0, 241, True, "3"])
def test_invalid_window_is_rejected_before_admission(stop):
    with pytest.raises(ValueError, match="WINDOW_INVALID"):
        validate_execution_window(
            {"version": "creation-execution-window.v1", "stop_after_chapter": stop},
            target_chapters=240,
        )
