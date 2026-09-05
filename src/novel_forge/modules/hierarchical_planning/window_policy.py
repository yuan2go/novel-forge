from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ChapterWindowPolicy:
    policy_id: str = "chapter-window"
    version: str = "1.0.0"
    maximum_chapters: int = 8

    def __post_init__(self) -> None:
        if (
            not isinstance(self.policy_id, str)
            or not self.policy_id.strip()
            or not isinstance(self.version, str)
            or not self.version.strip()
        ):
            raise ValueError("execution window policy identity is required")
        if type(self.maximum_chapters) is not int or self.maximum_chapters <= 0:
            raise ValueError("execution window maximum must be a positive integer")

    def snapshot(self) -> dict[str, object]:
        return {"schema_version": "chapter-window-policy.v1", **asdict(self)}

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self.snapshot(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any]) -> "ChapterWindowPolicy":
        value = dict(snapshot)
        if (
            set(value) != {"schema_version", "policy_id", "version", "maximum_chapters"}
            or value.pop("schema_version") != "chapter-window-policy.v1"
        ):
            raise ValueError("unknown frozen execution window policy")
        return cls(**value)

    def require_range(self, start: int, end: int) -> None:
        if type(start) is not int or type(end) is not int or start <= 0 or end < start:
            raise ValueError(
                "execution window requires a positive ordered chapter range"
            )
        if end - start + 1 > self.maximum_chapters:
            raise ValueError("execution window exceeds its frozen operating policy")

    def select(self, *, start: int, target: int, preferred: int) -> tuple[int, int]:
        if (
            type(start) is not int
            or type(target) is not int
            or start <= 0
            or type(preferred) is not int
            or preferred <= 0
            or target < start
        ):
            raise ValueError(
                "execution window preference and remaining range must be positive"
            )
        end = start + min(preferred, self.maximum_chapters, target - start + 1) - 1
        self.require_range(start, end)
        return start, end


LEGACY_CHAPTER_WINDOW_POLICY = ChapterWindowPolicy(version="legacy-three-to-eight")
