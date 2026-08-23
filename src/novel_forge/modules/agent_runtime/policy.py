"""Server-authoritative Tool policy resolution for Agent Harness admission."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .harness import (
    AgentToolKind,
    AgentToolSpec,
    AutonomousAgentRole,
)
from .production import canonical_policy_hash


_ROLE_SET = (
    AutonomousAgentRole.STUDIO_DIRECTOR,
    AutonomousAgentRole.RESEARCH_KNOWLEDGE,
)

SERVER_AGENT_TOOL_CATALOG: dict[str, AgentToolSpec] = {
    "narrative.query_accepted": AgentToolSpec(
        tool_name="narrative.query_accepted",
        kind=AgentToolKind.READ_ONLY_QUERY,
        input_schema_ref="schema:agent-tool:narrative-query-accepted:v1",
        output_schema_ref="schema:agent-tool:narrative-query-accepted-result:v1",
        allowed_roles=_ROLE_SET,
    ),
    "story_planning.generate_candidate": AgentToolSpec(
        tool_name="story_planning.generate_candidate",
        kind=AgentToolKind.TYPED_CAPABILITY,
        input_schema_ref="schema:agent-tool:story-planning-candidate:v1",
        output_schema_ref="schema:agent-tool:story-planning-candidate-result:v1",
        allowed_roles=(AutonomousAgentRole.STUDIO_DIRECTOR,),
        external_effect_required=True,
    ),
    "plan_change.submit": AgentToolSpec(
        tool_name="plan_change.submit",
        kind=AgentToolKind.AUTHORITY_COMMAND,
        input_schema_ref="schema:agent-tool:plan-change-submit:v1",
        output_schema_ref="schema:agent-tool:plan-change-submitted:v1",
        allowed_roles=(AutonomousAgentRole.STUDIO_DIRECTOR,),
        authority_command_type="plan_change.propose",
    ),
}


class ServerAgentHarnessPolicyResolver:
    """Freeze Definition/Role/Pack/Skill/Tool policy under PostgreSQL locks."""

    def __init__(
        self,
        database_url: str,
        *,
        production_model_binding: Mapping[str, Any] | None,
    ) -> None:
        self.database_url = database_url
        self.production_model_binding = (
            dict(production_model_binding) if production_model_binding else None
        )

    @property
    def production_bound(self) -> bool:
        return self.production_model_binding is not None

    def resolve_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        agent_id: str,
        role: AutonomousAgentRole,
        caller_tools: tuple[AgentToolSpec, ...],
        caller_skills: tuple[Mapping[str, Any], ...],
    ) -> tuple[
        tuple[AgentToolSpec, ...],
        tuple[Mapping[str, Any], ...],
        Mapping[str, Any],
    ]:
        if not self.production_bound:
            raise KernelError(
                "AGENT_HARNESS_PRODUCTION_MODEL_UNBOUND",
                "controlled Agent admission has no governed production model binding",
            )
        if not agent_id.strip():
            raise KernelError(
                "AGENT_DEFINITION_REQUIRED",
                "controlled Agent admission requires an active Agent Definition",
            )
        definition = uow.repositories.agent_runtime.lock_active_definition(agent_id)
        if str(definition["role"]).strip().upper() != role.value:
            raise KernelError(
                "AGENT_DEFINITION_ROLE_MISMATCH",
                "requested Agent role differs from the active Definition",
            )
        allowed_names = tuple(str(item) for item in definition["allowed_tools"])
        unknown = sorted(set(allowed_names) - set(SERVER_AGENT_TOOL_CATALOG))
        if unknown:
            raise KernelError(
                "AGENT_TOOL_POLICY_UNBOUND",
                "active Agent Definition names unbound production Tools: "
                + ", ".join(unknown),
            )
        resolved = tuple(
            SERVER_AGENT_TOOL_CATALOG[name]
            for name in allowed_names
            if role in SERVER_AGENT_TOOL_CATALOG[name].allowed_roles
        )
        if not resolved:
            raise KernelError(
                "AGENT_TOOL_POLICY_EMPTY",
                "active Agent Definition grants no Tools to the requested role",
            )
        if caller_tools and self._tool_payloads(caller_tools) != self._tool_payloads(
            resolved
        ):
            raise KernelError(
                "AGENT_CALLER_TOOL_POLICY_MISMATCH",
                "caller Tool policy is not identical to the server Authority snapshot",
            )
        skills: tuple[Mapping[str, Any], ...] = (
            {
                "skill_id": str(definition["skill_bundle_ref"]),
                "skill_version": f"definition:{int(definition['definition_version'])}",
                "skill_hash": str(definition["skill_bundle_hash"]),
            },
        )
        if caller_skills and tuple(dict(item) for item in caller_skills) != skills:
            raise KernelError(
                "AGENT_CALLER_SKILL_BINDING_MISMATCH",
                "caller Skill bindings differ from the active Definition snapshot",
            )
        policy = {
            "policy_version": "agent-harness-server-policy.v1",
            "authority": "POSTGRESQL_AGENT_DEFINITION",
            "agent_id": str(definition["agent_id"]),
            "agent_definition_version": int(definition["definition_version"]),
            "agent_definition_hash": str(definition["definition_hash"]),
            "agent_definition_activation_version": int(
                definition["activation_version"]
            ),
            "agent_runtime_contract_hash": str(definition["runtime_contract_hash"]),
            "role": role.value,
            "capability_pack_ref": str(definition["capability_pack_ref"]),
            "prompt_bundle_ref": str(definition["prompt_bundle_ref"]),
            "prompt_bundle_hash": str(definition["prompt_bundle_hash"]),
            "tool_policy_ref": str(definition["tool_policy_ref"]),
            "tool_policy_hash": str(definition["tool_policy_hash"]),
            "skill_bundle_ref": str(definition["skill_bundle_ref"]),
            "skill_bundle_hash": str(definition["skill_bundle_hash"]),
            "context_policy_ref": str(definition["context_policy_ref"]),
            "context_policy_hash": str(definition["context_policy_hash"]),
            "authority_policy": "SUBMIT_ONLY_NO_DIRECT_MUTATION",
            "tools": self._tool_payloads(resolved),
            "model_binding": dict(self.production_model_binding or {}),
            "skills_do_not_grant_authority": True,
        }
        return (
            resolved,
            skills,
            {**policy, "policy_hash": canonical_policy_hash(policy)},
        )

    @staticmethod
    def _tool_payloads(tools: tuple[AgentToolSpec, ...]) -> list[dict[str, Any]]:
        return [
            {
                **asdict(tool),
                "kind": tool.kind.value,
                "allowed_roles": [role.value for role in tool.allowed_roles],
            }
            for tool in tools
        ]


__all__ = ["SERVER_AGENT_TOOL_CATALOG", "ServerAgentHarnessPolicyResolver"]
