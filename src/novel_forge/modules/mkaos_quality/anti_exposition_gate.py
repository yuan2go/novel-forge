from __future__ import annotations

import re
from typing import Any


EXPOSITION_MARKERS = ("是指", "定义", "概念", "主要包括", "根据", "从理论上", "可以分为", "本文认为", "百科", "资料显示")
ACTION_MARKERS = ("冲突", "选择", "代价", "行动", "阻碍", "反转", "钩子", "对白", "场景", "利益")


def check_anti_exposition(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text") or payload.get("candidate_text") or payload.get("creative_principle") or "")
    compact = re.sub(r"\s+", "", text)
    exposition_hits = [marker for marker in EXPOSITION_MARKERS if marker in compact]
    action_hits = [marker for marker in ACTION_MARKERS if marker in compact]
    long_explanation = len(compact) > int(payload.get("long_exposition_chars", 180) or 180) and len(action_hits) < 2
    score = 1.0 - min(0.7, 0.16 * len(exposition_hits) + (0.25 if long_explanation else 0.0)) + min(0.2, 0.05 * len(action_hits))
    score = round(max(0.0, min(1.0, score)), 4)
    passed = score >= float(payload.get("threshold", 0.7))
    suggestions = []
    if not passed:
        suggestions = ["转成人物目标", "转成阻碍", "转成利益冲突", "转成选择代价", "转成章节钩子"]
    return {
        "passed": passed,
        "anti_exposition_score": score,
        "exposition_markers": exposition_hits,
        "action_markers": action_hits,
        "issues": [] if passed else [{"issue_type": "anti_encyclopedia", "severity": "high", "blocking": True}],
        "rewrite_suggestions": suggestions,
    }
