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
    "multidisciplinary-knowledge": "1.1.0",
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
        source_name = (
            "legacy-v1.md"
            if skill_id == "multidisciplinary-knowledge"
            and self.versions[skill_id] == "1.0.0"
            else "SKILL.md"
        )
        path = (self.skill_root / skill_id / source_name).resolve()
        if self.skill_root not in path.parents or not path.is_file():
            raise ValueError(f"Source analysis Skill is not available: {skill_id}")
        content = path.read_text(encoding="utf-8")
        match = re.search(r"(?m)^name:\s*([^\s]+)\s*$", content)
        if match is None or match.group(1) != skill_id:
            raise ValueError(f"Source analysis Skill identity mismatch: {skill_id}")
        digest = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
        version = self.versions[skill_id]
        if (
            expected_digest
            and digest != expected_digest
            and skill_id == "multidisciplinary-knowledge"
        ):
            legacy = self.skill_root / skill_id / "legacy-v1.md"
            if legacy.is_file():
                legacy_content = legacy.read_text(encoding="utf-8")
                legacy_digest = (
                    "sha256:"
                    + hashlib.sha256(legacy_content.encode("utf-8")).hexdigest()
                )
                if legacy_digest == expected_digest:
                    content, digest, source_name, version = (
                        legacy_content,
                        legacy_digest,
                        "legacy-v1.md",
                        "1.0.0",
                    )
        if expected_digest and digest != expected_digest:
            raise ValueError(
                f"Source analysis Skill materialization digest mismatch: {skill_id}"
            )
        return SourceMethodology(
            skill_id=skill_id,
            skill_version=version,
            content=content,
            content_digest=digest,
            source_ref=f"skills/{skill_id}/{source_name}",
        )


__all__ = [
    "METHODOLOGY_VERSIONS",
    "SourceMethodology",
    "SourceMethodologyRegistry",
]
