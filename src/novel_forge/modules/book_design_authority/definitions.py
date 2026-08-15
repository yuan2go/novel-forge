"""Operation definitions and execution classification for BookDesign Authority."""
from __future__ import annotations

from typing import Any


BOOK_DESIGN_DEFINITION_VERSION = "1.3.0"
BOOK_DESIGN_HANDLER_KEY = "novel_forge.book_design_authority.transaction"
BOOK_DESIGN_OPERATIONS = (
    "book.create",
    "book_design.propose",
    "book_design.decide",
    "book_design.activate",
)


def book_design_definitions(
    *, application_build_id: str, commit_sha: str
) -> tuple[dict[str, Any], ...]:
    definitions: list[dict[str, Any]] = []
    for name in BOOK_DESIGN_OPERATIONS:
        selector: dict[str, Any] | None = None
        if name == "book.create":
            selector = {
                "selector": "book_record", "output_key": "book.record",
                "role": "primary", "lifecycle": "ACTIVE",
                "eligibility": "ELIGIBLE", "governance": "CLEAR",
            }
        elif name == "book_design.propose":
            selector = {
                "selector": "book_design", "output_key": "book_design.candidate",
                "role": "candidate", "allowed_lifecycles": ["CANDIDATE"],
                "allowed_eligibility": ["ELIGIBLE", "INELIGIBLE"],
                "governance": "CLEAR",
            }
        elif name == "book_design.activate":
            selector = {
                "selector": "book_design", "output_key": "book_design.active",
                "role": "active", "lifecycle": "ACTIVE",
                "eligibility": "ELIGIBLE", "governance": "CLEAR",
            }
        event = f"authority.{name}.committed"
        definitions.append(
            {
                "name": name,
                "definition_version": BOOK_DESIGN_DEFINITION_VERSION,
                "family": "book_design_authority",
                "enabled": True,
                "command_schema": {
                    "type": "object",
                    "required": [
                        "project_id", "workspace_id", "book_id", "service_identity",
                        "expected_book_version", "payload",
                    ],
                    "properties": {
                        "project_id": {"type": "string"},
                        "workspace_id": {"type": "string"},
                        "book_id": {"type": "string"},
                        "service_identity": {"type": "string"},
                        "expected_book_version": {"type": "integer"},
                        "expected_current_design_asset_version_id": {"type": "string"},
                        "target_asset_version_id": {"type": "string"},
                        "migration_evidence": {"type": "object"},
                        "payload": {"type": "object"},
                    },
                    "additionalProperties": False,
                },
                "result_schema": {
                    "type": "object",
                    "required": ["book_id"],
                    "properties": {
                        "book_id": {"type": "string"},
                        "asset_version_id": {"type": "string"},
                        "decision_id": {"type": "string"},
                        "activation_id": {"type": "string"},
                    },
                },
                "handler_key": BOOK_DESIGN_HANDLER_KEY,
                "handler_contract_version": "book-design-authority-handler-v1",
                "application_build_id": application_build_id,
                "commit_sha": commit_sha,
                # The shared kernel persists this enum as ``transactional``;
                # the policy field below carries the architecture-facing
                # classification name used by Track B.
                "execution_mode": "transactional",
                "permissions": ["book_design.authority.execute"],
                "approval_policy": {"required": False, "policy_key": "domain-decision-record"},
                "idempotency_scope": "book:design",
                # Admission exposes project/workspace at the envelope level;
                # one workspace is authoritatively bound to one Book.
                "concurrency_key_template": "book-workspace:{workspace_id}:design",
                "retry_policy": {"max_attempts": 1, "mode": "client_replay_only"},
                "timeout_policy": {"operation_timeout_seconds": 60},
                "cancellation_policy": {"mode": "not_applicable_atomic_transaction"},
                "compensation_policy": {"supported": False, "reason": "append-only versions and decisions"},
                "irreversible_effect_policy": {"allowed": False},
                "external_capabilities": [],
                "policy": {
                    "execution_classification": "transaction_command",
                    "book_scope_required": True,
                    "legacy_writer": "disabled",
                    "silent_fallback": False,
                    "progressive_narrative_qualification": (
                        "independent_worker_required_for_book-design-v3"
                    ),
                },
                "completion_contract": {
                    "version": f"{name}.completion.v1",
                    "required_asset_selectors": [] if selector is None else [selector],
                    "required_qualifications": (
                        []
                        if selector is None or name == "book_design.propose"
                        else [{"decision": "ELIGIBLE"}]
                    ),
                    "required_evidence": ["trace", "audit"],
                    "required_outbox_events": [event],
                },
            }
        )
    return tuple(definitions)


__all__ = [
    "BOOK_DESIGN_DEFINITION_VERSION",
    "BOOK_DESIGN_HANDLER_KEY",
    "BOOK_DESIGN_OPERATIONS",
    "book_design_definitions",
]
