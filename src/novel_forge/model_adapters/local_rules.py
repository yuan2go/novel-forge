from __future__ import annotations

from typing import Any


class LocalRuleEngine:
    """Local rule checks that do not call external models."""

    def generate(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"text": prompt, "rules_applied": []}

    def analyze(self, text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        issues = []
        if len(text.strip()) < 40:
            issues.append("content_too_short")
        return {"issues": issues, "length": len(text)}

    def review(self, content: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        issues = []
        if "copy exact" in content.lower():
            issues.append("possible_copy_instruction")
        return {"score": 100 - len(issues) * 30, "issues": issues}

    def revise(self, content: str, review: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"plan": [f"fix {issue}" for issue in review.get("issues", [])]}

    def batch(self, prompts: list[str], context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return [self.analyze(prompt, context) for prompt in prompts]

    def health_check(self) -> dict[str, Any]:
        return {"model": "local-rule-engine", "ok": True, "external_api": False}
