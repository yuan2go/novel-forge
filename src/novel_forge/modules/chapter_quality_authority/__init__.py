"""Storage-free evidence contracts for Chapter Quality Authority."""
from .domain import (
    QUALITY_DIMENSIONS,
    QUALITY_GROUPS,
    build_chapter_quality_evidence,
    build_quality_group_evidence,
)

__all__ = [
    "QUALITY_DIMENSIONS", "QUALITY_GROUPS", "build_chapter_quality_evidence",
    "build_quality_group_evidence",
]
