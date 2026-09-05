from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError


READER_POLICY_OWNER = "READER_PROXY"


@dataclass(frozen=True, slots=True)
class ReaderProxyPolicy:
    policy_version: str = "reader-proxy-thresholds-v1"
    confusion: float = 0.75
    drop_risk: float = 0.75
    repetition_fatigue: float = 0.65
    continue_intent: float = 0.35
    trust: float = 0.45
    character_attachment: float = 0.45
    antagonist_pressure: float = 0.40
    payoff_satisfaction: float = 0.45
    ordinal_high: float = 0.70
    ordinal_medium: float = 0.40
    recap_confusion: float = 0.65
    recap_repetition_fatigue: float = 0.65
    revision_required_issue_count: int = 2
    human_review_major_count: int = 3

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError("Reader proxy policy requires a version")
        for name, value in asdict(self).items():
            if name == "policy_version":
                continue
            if name.endswith("_count"):
                if type(value) is not int or value <= 0:
                    raise ValueError("Reader proxy issue counts must be positive")
            elif (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not (math.isfinite(value) and 0 <= value <= 1)
            ):
                raise ValueError("Reader proxy thresholds must be finite probabilities")
        if self.ordinal_medium >= self.ordinal_high:
            raise ValueError("Reader proxy ordinal thresholds must be ordered")


def policy_from_snapshot(snapshot: Mapping[str, Any]) -> ReaderProxyPolicy:
    content = snapshot.get("policy")
    if (
        snapshot.get("owner") != READER_POLICY_OWNER
        or not isinstance(content, dict)
        or hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        != snapshot.get("policy_hash")
    ):
        raise KernelError(
            "READER_PROXY_POLICY_SNAPSHOT_INVALID", "frozen policy required"
        )
    return ReaderProxyPolicy(**content)
