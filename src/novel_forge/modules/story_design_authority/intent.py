from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.reality import narrative_hash


class ControlMode(StrEnum):
    AUTO = "AUTO"
    AUTHOR_SUPERVISED = "AUTHOR_SUPERVISED"
    REVIEW_MAJOR_DECISION = "REVIEW_MAJOR_DECISION"
    REVIEW_PLAN = "REVIEW_PLAN"
    REVIEW_CHAPTER = "REVIEW_CHAPTER"
    REVIEW_REALITY_COMMIT = "REVIEW_REALITY_COMMIT"
    MANUAL_DIRECTOR = "MANUAL_DIRECTOR"


INTENT_ROUTES = {
    "goal": ("BOOK", "ARC", "VOLUME", "NEAR_TERM", "CHAPTER"),
    "must_have": ("CHAPTER", "SCENE", "QUALITY"),
    "must_not": ("CHAPTER", "SCENE", "REALIZATION", "QUALITY"),
    "tone": ("REALIZATION", "QUALITY"),
    "pacing": ("ARC", "VOLUME", "NEAR_TERM", "CHAPTER", "SCENE", "QUALITY"),
    "relationship_direction": ("ARC", "CHAPTER", "SCENE"),
    "arc_constraint": ("ARC", "NEAR_TERM", "CHAPTER"),
    "theme_constraint": ("BOOK", "ARC", "CHAPTER", "QUALITY"),
    "ending_constraint": ("BOOK", "ARC", "QUALITY"),
    "allowed_deviation": ("NEAR_TERM", "CHAPTER", "SCENE", "QUALITY"),
}


@dataclass(frozen=True, slots=True)
class NarrativeIntent:
    source_text: str
    goal: str
    must_have: tuple[str, ...]
    must_not: tuple[str, ...]
    tone: str
    pacing: str
    relationship_direction: str
    arc_constraint: str
    theme_constraint: str
    ending_constraint: str
    allowed_deviation: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> NarrativeIntent:
        if (
            set(raw) != {"source_text", *INTENT_ROUTES}
            or any(
                not isinstance(raw[key], str) or not raw[key].strip()
                for key in ("source_text", "goal", "allowed_deviation")
            )
            or any(
                not isinstance(raw.get(key), str)
                for key in INTENT_ROUTES
                if key not in {"must_have", "must_not"}
            )
        ):
            raise KernelError(
                "NARRATIVE_INTENT_CONTRACT_INVALID",
                "Intent must retain exact source text, goal and explicit deviation policy",
            )
        for key in ("must_have", "must_not"):
            if not isinstance(raw[key], list) or any(
                not isinstance(v, str) or not v.strip() for v in raw[key]
            ):
                raise KernelError(
                    "NARRATIVE_INTENT_CONSTRAINT_INVALID",
                    "Intent constraints must be explicit nonempty strings",
                )
        if set(raw["must_have"]) & set(raw["must_not"]):
            raise KernelError(
                "NARRATIVE_INTENT_CONTRADICTION",
                "an identical requirement cannot be both required and forbidden",
            )
        return cls(
            **{
                k: tuple(v) if k in {"must_have", "must_not"} else v
                for k, v in raw.items()
            }
        )

    def route(self, *, target: str) -> dict[str, Any]:
        if target not in {
            layer for layers in INTENT_ROUTES.values() for layer in layers
        }:
            raise KernelError(
                "NARRATIVE_INTENT_ROUTE_INVALID", "unknown narrative abstraction target"
            )
        values = asdict(self)
        body = {
            "contract_version": "narrative-intent-projection.v1",
            "target": target,
            "intent_digest": narrative_hash(values),
            "constraints": {
                key: values[key]
                for key, layers in INTENT_ROUTES.items()
                if target in layers
            },
        }
        return {**body, "projection_digest": narrative_hash(body)}


def compile_narrative_intent(source_text: str) -> NarrativeIntent:
    if not isinstance(source_text, str) or not source_text.strip():
        raise KernelError(
            "NARRATIVE_INTENT_SOURCE_REQUIRED",
            "Intent compilation requires the exact source instruction",
        )
    aliases = {
        "目标": "goal",
        "必须": "must_have",
        "禁止": "must_not",
        "基调": "tone",
        "节奏": "pacing",
        "关系方向": "relationship_direction",
        "弧线约束": "arc_constraint",
        "主题约束": "theme_constraint",
        "结局约束": "ending_constraint",
        "允许偏离": "allowed_deviation",
        **{key: key for key in INTENT_ROUTES},
    }
    values: dict[str, Any] = {
        key: [] if key in {"must_have", "must_not"} else "" for key in INTENT_ROUTES
    }
    assigned: set[str] = set()
    for line in source_text.splitlines():
        if not line.strip():
            continue
        label, separator, text = line.strip().replace("：", ":", 1).partition(":")
        key = aliases.get(label.strip()) if separator else None
        if key is None or not text.strip():
            raise KernelError(
                "NARRATIVE_INTENT_INTERPRETATION_REQUIRED",
                "Each instruction needs a declared semantic label; unlabeled prose requires an explicit interpretation before activation",
            )
        text = text.strip()
        if key in {"must_have", "must_not"}:
            if text in values[key]:
                raise KernelError(
                    "NARRATIVE_INTENT_DUPLICATE_CONSTRAINT",
                    "A source constraint must occur once",
                )
            values[key].append(text)
        elif key in assigned:
            raise KernelError(
                "NARRATIVE_INTENT_AMBIGUOUS_SOURCE",
                "Scalar intent fields cannot silently overwrite an earlier instruction",
            )
        else:
            values[key] = text
        assigned.add(key)
    if not {"goal", "allowed_deviation"}.issubset(assigned):
        raise KernelError(
            "NARRATIVE_INTENT_INTERPRETATION_REQUIRED",
            "Intent requires an explicit goal and allowed deviation; the compiler does not invent either",
        )
    return NarrativeIntent.from_mapping({"source_text": source_text, **values})
