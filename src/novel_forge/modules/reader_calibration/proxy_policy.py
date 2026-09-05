from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ReaderProxyRule:
    dimension: str
    code: str
    high_is_bad: bool
    blocking: bool
    threshold: float


@dataclass(frozen=True, slots=True)
class ReaderProxyPolicy:
    version: str
    rules: tuple[ReaderProxyRule, ...]
    recap_confusion_threshold: float
    recap_repetition_threshold: float
    continuation_high_threshold: float
    continuation_medium_threshold: float
    trend_delta_threshold: float
    revision_required_blocking_count: int
    human_review_major_count: int

    def snapshot(self) -> dict[str, Any]:
        content = json.loads(json.dumps(asdict(self)))
        content.update(
            owner="ReaderCalibration",
            calibration_status="UNCALIBRATED_POLICY",
            evidence_class="READER_PROXY_ADVISORY",
            human_editorial_proof=False,
        )
        digest = hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return {**content, "content_hash": f"sha256:{digest}"}


READER_PROXY_POLICY_V1 = ReaderProxyPolicy(
    version="reader-proxy-policy-v1",
    rules=(
        ReaderProxyRule("confusion", "READER_CONFUSION_RISE", True, True, 0.75),
        ReaderProxyRule("drop_risk", "DROP_RISK_HIGH", True, True, 0.75),
        ReaderProxyRule("repetition_fatigue", "REPETITION_FATIGUE", True, False, 0.65),
        ReaderProxyRule("continue_intent", "CONTINUE_INTENT_LOW", False, True, 0.35),
        ReaderProxyRule("trust", "READER_TRUST_LOW", False, False, 0.45),
        ReaderProxyRule(
            "character_attachment", "CHARACTER_ATTACHMENT_LOW", False, False, 0.45
        ),
        ReaderProxyRule(
            "antagonist_pressure", "ANTAGONIST_PRESSURE_DROP", False, False, 0.40
        ),
        ReaderProxyRule(
            "payoff_satisfaction", "PAYOFF_SATISFACTION_LOW", False, False, 0.45
        ),
    ),
    recap_confusion_threshold=0.65,
    recap_repetition_threshold=0.65,
    continuation_high_threshold=0.7,
    continuation_medium_threshold=0.4,
    trend_delta_threshold=0.05,
    revision_required_blocking_count=2,
    human_review_major_count=3,
)


def resolve_reader_proxy_policy(
    snapshot: Mapping[str, Any] | None,
) -> ReaderProxyPolicy:
    if snapshot is None:
        return READER_PROXY_POLICY_V1
    if dict(snapshot) != READER_PROXY_POLICY_V1.snapshot():
        raise ValueError(
            "reader proxy policy version or content hash is not registered"
        )
    return READER_PROXY_POLICY_V1
