"""Explicit bridge from legacy static profiles into Agent Definition Authority.

The adapter only builds registration commands.  It never resolves production
Agents and cannot be used as a fallback when PostgreSQL resolution fails.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping


def _hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class LegacyAgentProfileBootstrapAdapter:
    """Translate one named static profile into an auditable registration payload."""

    profiles: Mapping[str, Mapping[str, Any]]

    compatibility_classification: str = "COMPATIBILITY_ADAPTER"
    production_registry: bool = False
    fallback_allowed: bool = False

    def registration_payload(
        self,
        *,
        agent_id: str,
        definition_version: int,
        capability_id: str,
        capability_version: int,
        execution_capability_id: str,
        execution_capability_hash: str,
        capability_pack_ref: str,
        prompt_bundle_ref: str,
        prompt_bundle_hash: str,
        skill_bundle_ref: str,
        skill_bundle_hash: str,
        tool_policy_ref: str,
        context_policy_ref: str,
    ) -> dict[str, Any]:
        if definition_version <= 0 or capability_version <= 0:
            raise ValueError("bootstrap versions must be positive")
        profile = self.profiles.get(agent_id)
        if profile is None:
            raise KeyError(f"legacy Agent profile does not exist: {agent_id}")
        profile = dict(profile)
        allowed_tools = tuple(str(item) for item in profile.get("allowed_tools") or ())
        forbidden = tuple(str(item) for item in profile.get("forbidden") or ())
        if not allowed_tools or not forbidden:
            raise ValueError("legacy profile lacks an explicit tool or prohibition policy")
        tool_policy = {
            "allowed_tools": allowed_tools,
            "forbidden": forbidden,
            "source": "AGENT_RUNTIME_PROFILES",
        }
        context_policy = {
            "allowed_context_types": tuple(
                str(item) for item in profile.get("allowed_write_types") or ()
            ),
            "raw_source_access": "FORBIDDEN",
            "source": "AGENT_RUNTIME_PROFILES",
        }
        capability = {
            "capability_id": capability_id,
            "version": capability_version,
            "domain": "legacy-bootstrap",
            "input_schema_ref": f"schema:{capability_id}:input@1",
            "output_schema_ref": f"schema:{capability_id}:candidate@1",
            "supported_message_types": ["PROPOSAL", "EVALUATION", "REVISION"],
            "supported_scope_types": ["book", "chapter"],
            "risk_class": "HIGH",
            "execution_requirements": {
                "production_execution_gateway_required": True,
                "domain_authority_commit_required": True,
            },
            "qualification_status": "UNQUALIFIED",
        }
        definition = {
            "agent_id": agent_id,
            "version": definition_version,
            "agent_type": str(profile.get("agent") or agent_id),
            "domain": "legacy-bootstrap",
            "role": str(profile.get("permission_profile") or "legacy-bootstrap"),
            "capability_refs": [f"{capability_id}@{capability_version}"],
            "input_contract_ref": capability["input_schema_ref"],
            "output_contract_ref": capability["output_schema_ref"],
            "authority_scope_ref": "authority:domain-candidate-only@1",
            "default_scope_policy_ref": "scope:explicit-frozen-assets@1",
            "allowed_tools": list(allowed_tools),
            "allowed_context_types": list(context_policy["allowed_context_types"]),
            "execution_policy_ref": "execution:pep-required@1",
            "approval_policy_ref": "approval:domain-authority@1",
            "quality_policy_ref": "quality:unqualified-bootstrap@1",
            "status": "CANDIDATE",
        }
        return {
            "capability": capability,
            "definition": definition,
            "execution_mapping": {
                "capability_id": capability_id,
                "capability_version": capability_version,
                "execution_capability_id": execution_capability_id,
                "execution_capability_hash": execution_capability_hash,
            },
            "runtime_contract": {
                "agent_id": agent_id,
                "definition_version": definition_version,
                "capability_pack_ref": capability_pack_ref,
                "prompt_bundle_ref": prompt_bundle_ref,
                "prompt_bundle_hash": prompt_bundle_hash,
                "skill_bundle_ref": skill_bundle_ref,
                "skill_bundle_hash": skill_bundle_hash,
                "tool_policy_ref": tool_policy_ref,
                "tool_policy_hash": _hash(tool_policy),
                "context_policy_ref": context_policy_ref,
                "context_policy_hash": _hash(context_policy),
                "definition_source": "BOOTSTRAP_ADAPTER",
            },
            "legacy_usage": {
                "classification": self.compatibility_classification,
                "source": "AGENT_RUNTIME_PROFILES",
                "silent_fallback": False,
                "production_registry": False,
            },
        }


__all__ = ["LegacyAgentProfileBootstrapAdapter"]
