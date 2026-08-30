from __future__ import annotations

from typing import Any


EMBEDDING_DEFINITION_NAME = "narrative.retrieval.embedding.project"
EMBEDDING_DEFINITION_VERSION = "1.0.0"
EMBEDDING_HANDLER_KEY = "novel_forge.context_builder.embedding_projection"
EMBEDDING_PROJECTION_VERSION = "accepted-retrieval-embedding-v1"


def embedding_projection_operation_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    return {
        "name": EMBEDDING_DEFINITION_NAME,
        "definition_version": EMBEDDING_DEFINITION_VERSION,
        "family": "retrieval_projection",
        "enabled": True,
        "command_schema": {"type": "object"},
        "result_schema": {"type": "object"},
        "input_contract": {"type": "object"},
        "output_contract": {"type": "object"},
        "handler_key": EMBEDDING_HANDLER_KEY,
        "handler_contract_version": "retrieval-embedding-handler-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "worker",
        "permissions": ["chapter.authority.execute"],
        "approval_policy": {"required": False},
        "idempotency_scope": "retrieval:embedding-projection",
        "concurrency_key_template": "book:{book_id}:retrieval-embedding",
        "retry_policy": {"max_attempts": 3},
        "timeout_policy": {"operation_timeout_seconds": 600},
        "cancellation_policy": {"mode": "cooperative"},
        "compensation_policy": {
            "supported": False,
            "reason": "rebuildable_derived_projection",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": ["model.retrieval"],
        "policy": {
            "authority": "postgresql",
            "projection": "rebuildable",
            "accepted_boundary_required": True,
        },
        "completion_contract": {
            "version": "retrieval.embedding.project.completion.v1",
            "required_asset_selectors": [
                {
                    "selector": "retrieval_embedding_candidate",
                    "output_key": "retrieval.embedding.candidate",
                    "role": "derived_projection_candidate",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                }
            ],
            "required_external_effects": [
                {"capability": "model.retrieval", "allowed_states": ["SUCCEEDED"]}
            ],
            "required_evidence": ["trace", "audit"],
            "required_audit_actions": ["retrieval.embedding.candidate.materialized"],
            "required_outbox_events": ["retrieval.embedding.candidate.materialized"],
        },
    }


__all__ = [
    "EMBEDDING_DEFINITION_NAME",
    "EMBEDDING_DEFINITION_VERSION",
    "EMBEDDING_HANDLER_KEY",
    "EMBEDDING_PROJECTION_VERSION",
    "embedding_projection_operation_definition",
]
