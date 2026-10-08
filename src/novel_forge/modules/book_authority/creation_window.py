
from typing import Any, Mapping


def validate_execution_window(
    value: Any, *, target_chapters: int
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"version", "stop_after_chapter"}:
        raise ValueError("CREATION_EXECUTION_WINDOW_INVALID")
    stop = value["stop_after_chapter"]
    if (
        value["version"] != "creation-execution-window.v1"
        or not isinstance(stop, int)
        or isinstance(stop, bool)
        or not 1 <= stop <= target_chapters
    ):
        raise ValueError("CREATION_EXECUTION_WINDOW_INVALID")
    return dict(value)


def execution_stop_chapter(policy: Mapping[str, Any], *, target_chapters: int) -> int:
    profile = (
        policy.get("creation_input_policy", {})
        .get("profiles", {})
        .get("production_profile", {})
        .get("content", {})
    )
    window = validate_execution_window(
        profile.get("execution_window"), target_chapters=target_chapters
    )
    return window["stop_after_chapter"] if window else target_chapters
