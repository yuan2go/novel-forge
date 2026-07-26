"""Immutable Prompt and Skill bundle contracts used by governed execution."""

from __future__ import annotations

from dataclasses import dataclass, fields
import hashlib
import json
import re
from typing import Any, Mapping


_SHA256 = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$", re.IGNORECASE)
_STABLE_ID = re.compile(r"^[a-z0-9][a-z0-9._:/-]*$", re.IGNORECASE)
_SECRET_VALUE = re.compile(
    r"(?:^|\s)(?:bearer\s+\S+|sk-[a-z0-9_-]{8,}|-----begin [a-z ]*private key-----)",
    re.IGNORECASE,
)


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _assert_no_secret(values: Mapping[str, Any]) -> None:
    for value in values.values():
        if isinstance(value, str) and _SECRET_VALUE.search(value):
            raise ValueError("execution bundle cannot contain secret material")
        if isinstance(value, Mapping):
            _assert_no_secret(value)
        if isinstance(value, (tuple, list)):
            _assert_no_secret({str(index): item for index, item in enumerate(value)})


class _VersionedBundle:
    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for item in fields(self):
            value = getattr(self, item.name)
            payload[item.name] = list(value) if isinstance(value, tuple) else value
        return payload

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()


@dataclass(frozen=True, slots=True)
class PromptBundle(_VersionedBundle):
    prompt_bundle_id: str
    prompt_version: str
    domain: str
    capability: str
    system_instruction_hash: str
    template_hash: str
    input_schema_ref: str
    output_schema_ref: str
    skill_bundle_ref: str
    context_policy_ref: str
    source_policy_ref: str
    compiler_version: str
    created_by_operation_id: str

    def __post_init__(self) -> None:
        values = self.to_dict()
        if any(
            not isinstance(value, str) or not value.strip()
            for value in values.values()
        ):
            raise ValueError("PromptBundle is incomplete")
        if not _STABLE_ID.fullmatch(self.capability):
            raise ValueError("PromptBundle capability is invalid")
        if not _STABLE_ID.fullmatch(self.domain):
            raise ValueError("PromptBundle domain is invalid")
        if not _SHA256.fullmatch(self.system_instruction_hash):
            raise ValueError("PromptBundle system instruction requires a SHA-256 hash")
        if not _SHA256.fullmatch(self.template_hash):
            raise ValueError("PromptBundle template requires a SHA-256 hash")
        _assert_no_secret(values)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PromptBundle":
        values = dict(payload)
        return cls(**{item.name: values.get(item.name) for item in fields(cls)})


@dataclass(frozen=True, slots=True)
class SkillBundle(_VersionedBundle):
    skill_bundle_id: str
    skill_version: str
    domain: str
    capability: str
    skill_refs: tuple[str, ...]
    skill_content_hashes: tuple[str, ...]
    tool_policy_ref: str
    created_by_operation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "skill_refs", tuple(str(item) for item in self.skill_refs))
        object.__setattr__(
            self,
            "skill_content_hashes",
            tuple(str(item) for item in self.skill_content_hashes),
        )
        if not all(
            (
                self.skill_bundle_id,
                self.skill_version,
                self.domain,
                self.capability,
                self.skill_refs,
                self.tool_policy_ref,
                self.created_by_operation_id,
            )
        ):
            raise ValueError("SkillBundle is incomplete")
        if len(self.skill_refs) != len(self.skill_content_hashes):
            raise ValueError("SkillBundle requires one content hash per skill reference")
        if len(set(self.skill_refs)) != len(self.skill_refs):
            raise ValueError("SkillBundle cannot contain duplicate skill versions")
        if any(not _SHA256.fullmatch(value) for value in self.skill_content_hashes):
            raise ValueError("SkillBundle content hashes must be SHA-256")
        _assert_no_secret(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SkillBundle":
        values = dict(payload)
        values["skill_refs"] = tuple(values.get("skill_refs") or ())
        values["skill_content_hashes"] = tuple(
            values.get("skill_content_hashes") or ()
        )
        return cls(**{item.name: values.get(item.name) for item in fields(cls)})


__all__ = ["PromptBundle", "SkillBundle"]
