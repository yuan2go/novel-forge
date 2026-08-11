"""Exact governed Skill artifacts used by Source intelligence execution."""
from __future__ import annotations

from pathlib import Path

from novel_forge.modules.capability_packs.artifacts import (
    ArtifactKind,
    ExplicitArtifactResolver,
    ResolvedArtifact,
    artifact_content_hash,
    canonical_artifact_json,
)


_SOURCE_SKILLS = {
    "hot-novel-deconstruction": (
        "2.0",
        "skills/hot-novel-deconstruction/SKILL.md",
    ),
    "published-fiction-craft-analysis": (
        "2.0",
        "skills/published-fiction-craft-analysis/SKILL.md",
    ),
    "classic-literary-depth-analysis": (
        "2.0",
        "skills/classic-literary-depth-analysis/SKILL.md",
    ),
    "multidisciplinary-knowledge": (
        "2.0",
        "skills/multidisciplinary-knowledge/SKILL.md",
    ),
    "platform-strategy-os": (
        "2.0",
        "skills/platform-strategy-os/SKILL.md",
    ),
    # anti-copy-abstraction is the Observation -> Candidate MKAOS method. It is
    # not used as a Source deconstruction analyzer.
    "anti-copy-abstraction": (
        "1.0",
        "skills/anti-copy-abstraction/SKILL.md",
    ),
}


def source_skill_version(skill_id: str) -> str:
    """Return the exact governed Source Skill version used in fingerprints."""

    try:
        return _SOURCE_SKILLS[skill_id][0]
    except KeyError as exc:
        raise ValueError(f"unsupported Source intelligence Skill: {skill_id}") from exc


def source_intelligence_artifact_resolver(
    repository_root: str | Path,
) -> ExplicitArtifactResolver:
    root = Path(repository_root).resolve()
    artifacts: list[ResolvedArtifact] = []
    for ref, (version, source_path) in sorted(_SOURCE_SKILLS.items()):
        relative = Path(source_path)
        target = (root / relative).resolve()
        if root not in target.parents:
            raise ValueError("Source Skill path escapes repository root")
        text = target.read_bytes().decode("utf-8", errors="strict").replace(
            "\r\n", "\n"
        )
        content = {"text": text}
        artifacts.append(
            ResolvedArtifact(
                kind=ArtifactKind.SKILL,
                ref=ref,
                version=version,
                content_hash=artifact_content_hash(content),
                content_json=canonical_artifact_json(content),
                source_identity=relative.as_posix(),
            )
        )
    return ExplicitArtifactResolver(artifacts)


__all__ = [
    "source_intelligence_artifact_resolver",
    "source_skill_version",
]
