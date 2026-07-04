from __future__ import annotations

from typing import Any


SOURCE_KIND_POLICIES: dict[str, dict[str, Any]] = {
    "professional_book": {
        "authorization": "owned",
        "copyright_boundary": "evidence_only",
        "allow_downstream_generation": False,
        "generation_rag_allowed": False,
        "raw_text_allowed_for_prose": False,
        "risk_level": "medium",
    },
    "classical_text": {
        "authorization": "public_domain",
        "copyright_boundary": "abstract_structure_only",
        "allow_downstream_generation": False,
        "generation_rag_allowed": False,
        "raw_text_allowed_for_prose": False,
        "risk_level": "low",
    },
    "classical_modern_parallel_corpus": {
        "authorization": "licensed",
        "copyright_boundary": "evidence_only",
        "allow_downstream_generation": False,
        "generation_rag_allowed": False,
        "raw_text_allowed_for_prose": False,
        "risk_level": "medium",
    },
    "webnovel_analysis": {
        "authorization": "owned",
        "copyright_boundary": "abstract_structure_only",
        "allow_downstream_generation": False,
        "generation_rag_allowed": False,
        "raw_text_allowed_for_prose": False,
        "risk_level": "high",
    },
    "mystery": {
        "authorization": "owned",
        "copyright_boundary": "abstract_mechanism_only",
        "allow_downstream_generation": False,
        "generation_rag_allowed": False,
        "raw_text_allowed_for_prose": False,
        "risk_level": "medium",
    },
    "manual_note": {
        "authorization": "owned",
        "copyright_boundary": "operator_note",
        "allow_downstream_generation": False,
        "generation_rag_allowed": False,
        "raw_text_allowed_for_prose": False,
        "risk_level": "low",
    },
}


def source_policy_for_kind(source_kind: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = dict(SOURCE_KIND_POLICIES.get(str(source_kind or "").strip(), SOURCE_KIND_POLICIES["manual_note"]))
    if overrides:
        policy.update({key: value for key, value in overrides.items() if value is not None})
    policy["allow_downstream_generation"] = bool(policy.get("allow_downstream_generation", False))
    policy["generation_rag_allowed"] = bool(policy.get("generation_rag_allowed", False))
    policy["raw_text_allowed_for_prose"] = bool(policy.get("raw_text_allowed_for_prose", False))
    return policy
