"""Chapter quality evidence contracts used by the Authority runtime."""

from novel_forge.modules.content_quality_loop.domain import (
    QUALITY_GATE_TYPES,
    evaluate_quality_evidence,
)

__all__ = ["QUALITY_GATE_TYPES", "evaluate_quality_evidence"]
