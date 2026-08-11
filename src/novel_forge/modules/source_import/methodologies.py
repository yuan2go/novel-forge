"""Exact canonical Skill materialization for Source analysis strategies."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re


METHODOLOGY_VERSIONS = {
    "hot-novel-deconstruction": "2.0.0",
    "hot-novel-business-deconstruction": "1.0.0",
    "published-fiction-craft-analysis": "1.0.0",
    "classic-literary-depth-analysis": "1.0.0",
    "multidisciplinary-knowledge": "1.0.0",
    "platform-strategy-os": "1.0.0",
    "anti-copy-abstraction": "1.0.0",
}


@dataclass(frozen=True, slots=True)
class SourceMethodology:
    skill_id: str
    skill_version: str
    content: str
    content_digest: str
    source_ref: str


class SourceMethodologyRegistry:
    """Loads root Skill sources and refuses generated/runtime copies."""

    def __init__(
        self,
        skill_root: Path,
        *,
        versions: dict[str, str] | None = None,
    ) -> None:
        self.skill_root = skill_root.resolve()
        self.versions = dict(METHODOLOGY_VERSIONS if versions is None else versions)
        if ".claude" in self.skill_root.parts:
            raise ValueError("generated runtime Skills cannot be methodology authority")

    def require(self, skill_id: str, *, expected_digest: str = "") -> SourceMethodology:
        if skill_id not in self.versions:
            raise ValueError(f"Source analysis Skill is not governed: {skill_id}")
        path = (self.skill_root / skill_id / "SKILL.md").resolve()
        if self.skill_root not in path.parents or not path.is_file():
            raise ValueError(f"Source analysis Skill is not available: {skill_id}")
        content = path.read_text(encoding="utf-8")
        match = re.search(r"(?m)^name:\s*([^\s]+)\s*$", content)
        if match is None or match.group(1) != skill_id:
            raise ValueError(f"Source analysis Skill identity mismatch: {skill_id}")
        digest = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
        if expected_digest and digest != expected_digest:
            raise ValueError(
                f"Source analysis Skill materialization digest mismatch: {skill_id}"
            )
        return SourceMethodology(
            skill_id=skill_id,
            skill_version=self.versions[skill_id],
            content=content,
            content_digest=digest,
            source_ref=f"skills/{skill_id}/SKILL.md",
        )


__all__ = [
    "METHODOLOGY_VERSIONS",
    "SourceMethodology",
    "SourceMethodologyRegistry",
]
