from __future__ import annotations

import re
from typing import Any


def evaluate_draft_quality(text: str) -> dict[str, Any]:
    checks = [
        _check_character_motivation(text),
        _check_causal_chain(text),
        _check_rhythm_density(text),
        _check_style_consistency(text),
        _check_foreshadowing_or_hook(text),
        _check_chapter_hook(text),
    ]
    passed_count = len([check for check in checks if check["passed"]])
    score = round((passed_count / len(checks)) * 100, 2) if checks else 0.0
    return {
        "passed": passed_count == len(checks),
        "score": score,
        "checks": checks,
        "blocked_dimensions": [check["dimension"] for check in checks if not check["passed"]],
    }


def gate_issues(gate: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for check in gate.get("checks", []):
        if not isinstance(check, dict) or check.get("passed"):
            continue
        issues.append(
            {
                "dimension": check.get("dimension", "creative_gate"),
                "severity": check.get("severity", "medium"),
                "message": check.get("message", ""),
                "recommendation": check.get("recommendation", ""),
                "reviewer": "local-creative-gate",
            }
        )
    return issues


def _check_character_motivation(text: str) -> dict[str, Any]:
    hits = _keyword_count(text, ["必须", "为了", "目标", "动机", "选择", "代价", "want", "need", "must", "because"])
    return _check(
        "character_motivation_chain",
        hits >= 1,
        "Character motivation pressure is not explicit enough.",
        "Add a visible goal, pressure, choice, or cost tied to the protagonist.",
        "high",
    )


def _check_causal_chain(text: str) -> dict[str, Any]:
    hits = _keyword_count(text, ["因为", "所以", "导致", "于是", "但", "却", "therefore", "because", "so", "but"])
    return _check(
        "causal_chain",
        hits >= 1,
        "Cause-and-effect language is too weak.",
        "Make one action visibly trigger a consequence before the chapter hook.",
        "high",
    )


def _check_rhythm_density(text: str) -> dict[str, Any]:
    sentences = _sentences(text)
    average_length = sum(len(sentence) for sentence in sentences) / len(sentences) if sentences else 0
    passed = len(sentences) >= 3 and average_length <= 120
    return _check(
        "rhythm_density",
        passed,
        "Scene rhythm may be too thin or too expository.",
        "Use at least three functional beats and keep sentence density readable.",
        "medium",
    )


def _check_style_consistency(text: str) -> dict[str, Any]:
    passed = "TODO" not in text and "lorem" not in text.lower() and len(set(_sentences(text))) == len(_sentences(text))
    return _check(
        "style_consistency",
        passed,
        "Draft contains placeholder text or repeated sentence patterns.",
        "Remove placeholders and repeated prose before downstream revision.",
        "medium",
    )


def _check_foreshadowing_or_hook(text: str) -> dict[str, Any]:
    hits = _keyword_count(text, ["线索", "伏笔", "钩子", "悬念", "门缝", "钟", "key", "clue", "hook", "mystery"])
    return _check(
        "foreshadowing_setup",
        hits >= 1,
        "No clear clue, hook, or foreshadowing object was detected.",
        "Add a concrete object, clue, or unresolved signal that can be tracked later.",
        "medium",
    )


def _check_chapter_hook(text: str) -> dict[str, Any]:
    sentences = _sentences(text)
    last = sentences[-1] if sentences else ""
    passed = len(last) >= 8 and _keyword_count(last, ["?", "？", "忽然", "传来", "发现", "打开", "留下", "hook", "clue"]) >= 1
    return _check(
        "chapter_hook",
        passed,
        "Chapter ending hook is not strong enough.",
        "End with an unresolved question, new obligation, or concrete reversal.",
        "high",
    )


def _check(dimension: str, passed: bool, message: str, recommendation: str, severity: str) -> dict[str, Any]:
    return {
        "dimension": dimension,
        "passed": passed,
        "severity": severity,
        "message": "" if passed else message,
        "recommendation": "" if passed else recommendation,
    }


def _sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in re.split(r"[。！？.!?\n]+", text) if sentence.strip()]


def _keyword_count(text: str, keywords: list[str]) -> int:
    lower = text.lower()
    return sum(lower.count(keyword.lower()) for keyword in keywords)
