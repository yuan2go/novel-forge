from __future__ import annotations

from typing import Any


class MockModelAdapter:
    """Deterministic model adapter used by tests and local demos."""

    name = "mock-model"

    def generate(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = context or {}
        return {
            "model": self.name,
            "text": f"Mock generation for: {prompt[:80]}",
            "context_keys": sorted(context.keys()),
        }

    def analyze(self, text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        words = [part for part in text.replace("\n", " ").split(" ") if part]
        return {
            "model": self.name,
            "word_count": len(words),
            "summary": text[:240],
            "patterns": [
                "delayed revelation",
                "escalating conflict",
                "chapter-end hook",
            ],
        }

    def review(self, content: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        score = 72 if len(content.strip()) > 80 else 58
        return {
            "model": self.name,
            "score": score,
            "strengths": ["clear forward motion", "visible chapter hook"],
            "weaknesses": ["mock draft needs richer sensory detail"],
            "issues": [
                {
                    "dimension": "originality_boundary",
                    "severity": "medium",
                    "message": "Confirm that all reference-derived patterns stay abstract.",
                }
            ],
            "risk_level": "medium",
            "revision_suggestions": [
                "increase causal links between decision and consequence",
                "add one concrete sensory beat before the hook",
            ],
            "next_action": "revise",
        }

    def revise(self, content: str, review: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "model": self.name,
            "plan": [
                "tighten the opening problem statement",
                "strengthen motivation chain",
                "verify copyright boundary before final draft",
            ],
            "based_on_score": review.get("score", 0),
        }

    def batch(self, prompts: list[str], context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return [self.generate(prompt, context) for prompt in prompts]

    def health_check(self) -> dict[str, Any]:
        return {"model": self.name, "ok": True, "external_api": False}
