from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any


def near_duplicate_score(left: str, right: str) -> dict[str, Any]:
    score = SequenceMatcher(None, str(left or ""), str(right or "")).ratio()
    return {"similarity": round(score, 4), "near_duplicate": score >= 0.82}
