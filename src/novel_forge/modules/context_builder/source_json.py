from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


@dataclass(frozen=True)
class _Number:
    lexeme: str


def loads(text: str) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise KernelError("CONTEXT_SOURCE_JSON_AMBIGUOUS", "original JSON contains duplicate fields; recover the exact source and resolve its representation before rebuilding")
            result[key] = value
        return result

    def finite(value):
        raise KernelError("CONTEXT_SOURCE_JSON_NONFINITE", "original JSON contains a nonfinite number; recover its source instead of changing the value")

    return json.loads(text, object_pairs_hook=unique, parse_int=_Number, parse_float=_Number, parse_constant=finite)


def dumps(value: Any) -> str:
    # WHY: Numeric lexemes survive visibility filtering without a float round trip or string coercion.
    if isinstance(value, _Number):
        return value.lexeme
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(key, ensure_ascii=False) + ":" + dumps(child) for key, child in sorted(value.items())) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(dumps(child) for child in value) + "]"
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
