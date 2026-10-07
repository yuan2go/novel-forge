from __future__ import annotations
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Protocol
from novel_forge.modules.production_execution.security import assert_no_inline_secrets

_FLOATING = re.compile(
    r"(?:^|[:/@._-])"
    r"(latest|current|active-latest|stable|main|master|head|tip|trunk|nightly)$",
    re.IGNORECASE,
)


class ArtifactKind(StrEnum):
    SKILL = "SKILL"
    PROMPT_SYSTEM_INSTRUCTION = "PROMPT_SYSTEM_INSTRUCTION"
    PROMPT_TEMPLATE = "PROMPT_TEMPLATE"
    SCHEMA = "SCHEMA"
    CONTEXT_POLICY = "CONTEXT_POLICY"
    SOURCE_POLICY = "SOURCE_POLICY"
    TOOL_POLICY = "TOOL_POLICY"
    VALIDATION_POLICY = "VALIDATION_POLICY"
    COMMIT_POLICY = "COMMIT_POLICY"
    TIMEOUT_POLICY = "TIMEOUT_POLICY"
    BUDGET_POLICY = "BUDGET_POLICY"
    APPROVAL_POLICY = "APPROVAL_POLICY"
    COMPENSATION_POLICY = "COMPENSATION_POLICY"
    PROTOCOL = "PROTOCOL"
    RULE = "RULE"
    KNOWLEDGE = "KNOWLEDGE"
    TEMPLATE = "TEMPLATE"


def canonical_artifact_json(content: Any) -> str:
    return json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def artifact_content_hash(content: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(canonical_artifact_json(content).encode("utf-8")).hexdigest()
    )


def is_floating_version(value: str) -> bool:
    return bool(_FLOATING.search(value.strip()))


@dataclass(frozen=True, slots=True)
class ResolvedArtifact:
    kind: ArtifactKind
    ref: str
    version: str
    content_hash: str
    content_json: str
    source_identity: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "ref": self.ref,
            "version": self.version,
            "content_hash": self.content_hash,
            "content": json.loads(self.content_json),
            "source_identity": self.source_identity,
        }


class ArtifactResolver(Protocol):
    def resolve(
        self, kind: ArtifactKind, ref: str, version: str
    ) -> ResolvedArtifact: ...

    def snapshot_hash(self) -> str: ...


class ExplicitArtifactResolver:

    def __init__(self, artifacts: Iterable[ResolvedArtifact]) -> None:
        values: dict[tuple[ArtifactKind, str, str], ResolvedArtifact] = {}
        for artifact in artifacts:
            if is_floating_version(artifact.version) or is_floating_version(
                artifact.ref
            ):
                raise ValueError("floating artifact versions are forbidden")
            if artifact.content_hash != artifact_content_hash(
                json.loads(artifact.content_json)
            ):
                raise ValueError("artifact catalog content hash mismatch")
            assert_no_inline_secrets(
                json.loads(artifact.content_json),
                label=f"CapabilityPackArtifact:{artifact.ref}",
            )
            key = (artifact.kind, artifact.ref, artifact.version)
            existing = values.get(key)
            if existing is not None and existing != artifact:
                raise ValueError(
                    "artifact identity is bound to different content or provenance"
                )
            values[key] = artifact
        self._values = MappingProxyType(values)

    def resolve(self, kind: ArtifactKind, ref: str, version: str) -> ResolvedArtifact:
        if is_floating_version(ref) or is_floating_version(version):
            raise ValueError("floating artifact versions are forbidden")
        matching_identity = [
            item for key, item in self._values.items() if key[1:] == (ref, version)
        ]
        if matching_identity and (kind, ref, version) not in self._values:
            raise TypeError(f"artifact kind mismatch for {ref}@{version}")
        try:
            return self._values[(kind, ref, version)]
        except KeyError as exc:
            versions = sorted(
                key[2] for key in self._values if key[0] is kind and key[1] == ref
            )
            if versions:
                raise LookupError(
                    f"artifact version unresolved: {ref}@{version}"
                ) from exc
            raise KeyError(f"artifact not found: {kind.value}:{ref}@{version}") from exc

    def artifacts(self) -> tuple[ResolvedArtifact, ...]:
        return tuple(
            self._values[key]
            for key in sorted(
                self._values, key=lambda item: (item[0].value, item[1], item[2])
            )
        )

    def snapshot_hash(self) -> str:
        payload = [
            {
                "kind": item.kind.value,
                "ref": item.ref,
                "version": item.version,
                "content_hash": item.content_hash,
                "source_identity": item.source_identity,
            }
            for item in self.artifacts()
        ]
        return artifact_content_hash({"artifacts": payload})

    @classmethod
    def from_catalog_file(
        cls, repository_root: str | Path, catalog_path: str | Path
    ) -> "ExplicitArtifactResolver":
        root = Path(repository_root).resolve()
        catalog = Path(catalog_path)
        if not catalog.is_absolute():
            catalog = root / catalog
        payload = _load_unique_json(catalog)
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema_version")
            != "novelos.capability_pack.artifact_catalog.v1"
        ):
            raise ValueError("artifact catalog schema is unsupported")
        entries = payload.get("artifacts")
        if not isinstance(entries, list):
            raise ValueError("artifact catalog requires an artifacts array")
        artifacts: list[ResolvedArtifact] = []
        for index, raw in enumerate(entries):
            if not isinstance(raw, Mapping):
                raise ValueError(f"artifact catalog entry {index} must be an object")
            kind = ArtifactKind(str(raw.get("kind") or ""))
            ref = str(raw.get("ref") or "")
            version = str(raw.get("version") or "")
            if not ref or not version:
                raise ValueError("artifact ref and version are required")
            has_content = "content" in raw
            has_path = "source_path" in raw
            if has_content == has_path:
                raise ValueError("artifact requires exactly one content source")
            if has_path:
                relative = Path(str(raw["source_path"]))
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("artifact source_path must be repository-relative")
                target = (root / relative).resolve()
                if root not in target.parents:
                    raise ValueError("artifact source escapes repository root")
                text = target.read_bytes().decode("utf-8", errors="strict")
                content: Any = {"text": text.replace("\r\n", "\n")}
                source_identity = relative.as_posix()
            else:
                content = raw["content"]
                source_identity = (
                    f"catalog:{catalog.relative_to(root).as_posix()}#"
                    f"{kind.value}:{ref}@{version}"
                )
            assert_no_inline_secrets(content, label=f"CapabilityPackArtifact:{ref}")
            content_json = canonical_artifact_json(content)
            artifacts.append(
                ResolvedArtifact(
                    kind=kind,
                    ref=ref,
                    version=version,
                    content_hash=artifact_content_hash(content),
                    content_json=content_json,
                    source_identity=source_identity,
                )
            )
        return cls(artifacts)


def exact_ref_version(ref: str) -> str:

    if is_floating_version(ref):
        raise ValueError("floating artifact versions are forbidden")
    match = re.search(r"(?:^|[:.-])(v?[0-9]+(?:\.[0-9]+){0,2})$", ref)
    if match is None:
        raise ValueError(f"artifact ref has no exact version: {ref}")
    return match.group(1)


def _load_unique_json(path: Path) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate artifact catalog key: {key}")
            value[key] = item
        return value

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number is forbidden: {value}")

    return json.loads(
        path.read_bytes().decode("utf-8", errors="strict"),
        object_pairs_hook=unique,
        parse_constant=reject_constant,
    )


def _artifact(
    kind: ArtifactKind,
    ref: str,
    version: str,
    content: Any,
    source_identity: str,
) -> ResolvedArtifact:
    return ResolvedArtifact(
        kind=kind,
        ref=ref,
        version=version,
        content_hash=artifact_content_hash(content),
        content_json=canonical_artifact_json(content),
        source_identity=source_identity,
    )


def default_chapter_artifact_resolver(
    repository_root: str | Path, *, include_current_contracts: bool = True,
) -> ExplicitArtifactResolver:

    root = Path(repository_root).resolve()
    artifacts: list[ResolvedArtifact] = []
    skill_sources = (
        ("chapter-outline", "chapter-plan-skill-v1", "skills/chapter-outline/legacy-v1.md"),
        ("chapter-outline", "chapter-plan-skill-v2", "skills/chapter-outline/legacy-calibration-20261003.md"),
        (
            "context-builder-source-isolation",
            "context-builder-source-isolation-v1",
            "skills/context-builder-source-isolation/legacy-calibration-20261003.md",
        ),
        ("prose-generation", "prose-generation-v1", "skills/prose-generation/legacy-v1.md"),
        ("prose-generation", "prose-generation-v2", "skills/prose-generation/legacy-v2.md"),
        ("prose-generation", "prose-generation-v3", "skills/prose-generation/legacy-calibration-20261003.md"),
        ("quality-review", "quality-review-v1", "skills/quality-review/legacy-v1.md"),
        ("quality-review", "quality-review-v2", "skills/quality-review/legacy-calibration-20261003.md"),
        (
            "canon-continuity-graph",
            "canon-continuity-graph-v1",
            "skills/canon-continuity-graph/legacy-v1.md",
        ),
        (
            "canon-continuity-graph",
            "canon-continuity-graph-v2",
            "skills/canon-continuity-graph/SKILL.md",
        ),
        (
            "agent-loop-governance",
            "agent-loop-governance-v1",
            "skills/agent-loop-governance/SKILL.md",
        ),
        ("chapter-outline", "chapter-plan-skill-v3", "skills/chapter-outline/SKILL.md"),
        ("prose-generation", "prose-generation-v4", "skills/prose-generation/SKILL.md"),
        ("quality-review", "quality-review-v3", "skills/quality-review/SKILL.md"),
        ("context-builder-source-isolation", "context-builder-source-isolation-v2", "skills/context-builder-source-isolation/SKILL.md"),
    )
    for ref, version, source in skill_sources:
        text = (root / source).read_bytes().decode("utf-8", errors="strict")
        artifacts.append(
            _artifact(
                ArtifactKind.SKILL,
                ref,
                version,
                {"text": text.replace("\r\n", "\n")},
                source,
            )
        )
    for kind, ref, version, source in (
        (
            ArtifactKind.PROMPT_SYSTEM_INSTRUCTION,
            "prompt-system:chapter-generation-pack",
            "v1",
            "config/capability_packs/artifacts/chapter_generation_system_instruction_v1.md",
        ),
        (
            ArtifactKind.PROMPT_SYSTEM_INSTRUCTION,
            "prompt-system:chapter-generation-pack",
            "v2",
            "config/capability_packs/artifacts/chapter_generation_system_instruction_v2.md",
        ),
        (
            ArtifactKind.PROMPT_TEMPLATE,
            "prompt-template:chapter-generation-pack",
            "v2",
            "config/capability_packs/artifacts/chapter_generation_template_v2.md",
        ),
        (
            ArtifactKind.PROMPT_TEMPLATE,
            "prompt-template:chapter-generation-pack",
            "v3",
            "config/capability_packs/artifacts/chapter_generation_template.md",
        ),
        (
            ArtifactKind.PROMPT_TEMPLATE,
            "prompt-template:chapter-generation-pack",
            "v4",
            "config/capability_packs/artifacts/chapter_generation_template.md",
        ),
        (
            ArtifactKind.PROMPT_TEMPLATE,
            "prompt-template:chapter-generation-pack",
            "v5",
            "config/capability_packs/artifacts/chapter_generation_template_v5.md",
        ),
        (
            ArtifactKind.PROMPT_SYSTEM_INSTRUCTION,
            "prompt-system:agent-session-pack",
            "v1",
            "config/capability_packs/artifacts/agent_session_system_instruction.md",
        ),
        (
            ArtifactKind.PROMPT_TEMPLATE,
            "prompt-template:agent-session-pack",
            "v1",
            "config/capability_packs/artifacts/agent_session_template.md",
        ),
        (
            ArtifactKind.PROMPT_SYSTEM_INSTRUCTION,
            "prompt-system:chapter-generation-pack",
            "v3",
            "config/capability_packs/artifacts/chapter_generation_system_instruction.md",
        ),
        (
            ArtifactKind.PROMPT_TEMPLATE,
            "prompt-template:chapter-generation-pack",
            "v6",
            "config/capability_packs/artifacts/chapter_generation_template_v6.md",
        ),
        (
            ArtifactKind.PROMPT_TEMPLATE,
            "prompt-template:chapter-generation-pack",
            "v7",
            "config/capability_packs/artifacts/chapter_generation_template_v7.md",
        ),
        (
            ArtifactKind.PROMPT_TEMPLATE,
            "prompt-template:chapter-generation-pack",
            "v8",
            "config/capability_packs/artifacts/chapter_generation_template_v8.md",
        ),
        (
            ArtifactKind.PROMPT_TEMPLATE,
            "prompt-template:chapter-generation-pack",
            "v9",
            "config/capability_packs/artifacts/chapter_generation_template_v9.md",
        ),
        (
            ArtifactKind.PROMPT_TEMPLATE,
            "prompt-template:chapter-generation-pack",
            "v10",
            "config/capability_packs/artifacts/chapter_generation_template_v10.md",
        ),
        (
            ArtifactKind.PROMPT_TEMPLATE,
            "prompt-template:chapter-generation-pack",
            "v11",
            "config/capability_packs/artifacts/chapter_generation_template_v11.md",
        ),
        (
            ArtifactKind.PROMPT_TEMPLATE,
            "prompt-template:chapter-generation-pack",
            "v12",
            "config/capability_packs/artifacts/chapter_generation_template_v12.md",
        ),
        (
            ArtifactKind.PROMPT_SYSTEM_INSTRUCTION,
            "prompt-system:model-reference-creation",
            "v1",
            "config/capability_packs/artifacts/model_reference_system_instruction_v1.md",
        ),
        (
            ArtifactKind.PROMPT_TEMPLATE,
            "prompt-template:model-reference-creation",
            "v1",
            "config/capability_packs/artifacts/model_reference_template_v1.md",
        ),
    ):
        if not include_current_contracts and ref == "prompt-template:chapter-generation-pack" and version == "v12":
            continue
        text = (root / source).read_bytes().decode("utf-8", errors="strict")
        artifacts.append(
            _artifact(kind, ref, version, {"text": text.replace("\r\n", "\n")}, source)
        )

    signed_catalog = ExplicitArtifactResolver.from_catalog_file(
        root,
        "config/capability_packs/artifacts/chapter_generation_contract_catalog.json",
    )
    artifacts.extend(signed_catalog.artifacts())
    artifacts.extend((
        _artifact(ArtifactKind.SCHEMA, "schema:model-reference-creation-input:v1", "v1",
            {"type": "object", "required": ["model_reference", "subject", "author_baseline", "context"],
             "properties": {"model_reference": {"type": "object"}, "subject": {"type": "object"},
                 "author_baseline": {"type": "object"}, "context": {"type": "object"},
                 "source_evaluations": {"type": "array", "minItems": 2, "maxItems": 2}},
             "additionalProperties": False}, "native:model-reference-creation-input-v1"),
        _artifact(ArtifactKind.SCHEMA, "schema:model-reference-creation-output:v1", "v1",
            {"type": "object", "required": ["status", "score_range", "findings"],
             "properties": {"status": {"enum": ["PASSED", "FAILED", "UNCERTAIN"]},
                 "score_range": {"type": "array", "minItems": 2, "maxItems": 2,
                     "items": {"type": "integer", "minimum": 0, "maximum": 100}},
                 "findings": {"type": "array", "items": {"type": "string"}},
                 "evaluation": {"type": "object"}}, "additionalProperties": False},
            "native:model-reference-creation-output-v1"),
    ))
    return ExplicitArtifactResolver(artifacts)


__all__ = [
    "ArtifactKind",
    "ArtifactResolver",
    "ExplicitArtifactResolver",
    "ResolvedArtifact",
    "artifact_content_hash",
    "canonical_artifact_json",
    "default_chapter_artifact_resolver",
    "exact_ref_version",
    "is_floating_version",
]
