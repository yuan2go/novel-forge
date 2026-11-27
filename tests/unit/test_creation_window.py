import pytest
from novel_forge.modules.book_authority.creation_window import (
    validate_execution_window,
    execution_stop_chapter,
    extend_delivery_window,
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


@pytest.mark.parametrize("version,stop,key", [(True, 40, "key"), (-1, 40, "key"), (1, True, "key"), (1, "40", "key"), (1, 40, " ")])
def test_extension_invalid_command_never_reaches_authority(version, stop, key):
    with pytest.raises(ValueError, match="COMMAND_INVALID"):
        extend_delivery_window(None, "book-run", principal=None, expected_version=version,
            stop_after_chapter=stop, idempotency_key=key)


def test_extension_cli_requires_exact_checkpoint_and_retained_key():
    from novel_forge.cli.authority import _authority_parser
    parsed = _authority_parser().parse_args(["authority-manuscript", "extend-delivery-window",
        "--book-run-id", "book-run", "--stop-after-chapter", "40", "--expected-version", "7", "--idempotency-key", "extend-40"])
    assert (parsed.stop_after_chapter, parsed.expected_version, parsed.idempotency_key) == (40, 7, "extend-40")


def test_extension_api_rejects_coerced_target():
    from pydantic import ValidationError
    from novel_forge.api.routers.chapter_editor import DeliveryWindowRequest
    with pytest.raises(ValidationError):
        DeliveryWindowRequest(project_id="p", book_run_id="b", expected_version=1, idempotency_key="k", stop_after_chapter=True)
