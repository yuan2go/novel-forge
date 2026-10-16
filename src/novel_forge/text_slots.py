"""INVARIANT: ordered text slots preserve their exact text and whitespace separators."""

from typing import Any, Mapping, Sequence


def text_slot_separators(slots: Sequence[Mapping[str, Any]], separators: Any = None) -> list[str]:
    count = max(0, len(slots) - 1)
    if separators is None:
        return ["\n\n"] * count
    if (not isinstance(separators, list) or len(separators) != count
            or any(not isinstance(value, str) or (value != "" and not value.isspace()) for value in separators)):
        raise ValueError("explicit Scene separators must be whitespace in frozen slot order")
    return list(separators)


def serialize_text_slots(slots: Sequence[Mapping[str, Any]], separators: Any = None) -> str:
    joins = text_slot_separators(slots, separators)
    return "".join((joins[index - 1] if index else "") + item["text"]
                   for index, item in enumerate(slots))
