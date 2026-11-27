from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from novel_forge.modules.production_execution.domain_execution import (
    CandidateKind,
    DomainExecutionEvidence,
    DomainExecutionPort,
    execute_domain_candidate,
)
from novel_forge.modules.production_execution.agent_workspace_backend import (
    AgentWorkspaceExecutionContract,
)


class AgentResultKind(StrEnum):
    PATCH_CANDIDATE = "patch_candidate"
    STRUCTURED_DECISION = "structured_decision"
    ANALYSIS_REPORT = "analysis_report"
    PROPOSED_ASSET_VERSION = "proposed_asset_version"
    WORKSPACE_MANIFEST = "workspace_manifest"


@dataclass(frozen=True, slots=True)
class AgentWorkspaceResultCandidate:
    result_kind: AgentResultKind
    result: Mapping[str, Any]
    evidence: DomainExecutionEvidence
    commit_status: str = "NOT_COMMITTED"

    def __post_init__(self) -> None:
        if not self.result:
            raise ValueError("agent workspace result candidate cannot be empty")
        if self.commit_status != "NOT_COMMITTED":
            raise ValueError("agent workspace execution cannot claim domain commit")
        forbidden_claims = {
            "committed",
            "commit_succeeded",
            "active_asset_version_id",
            "activation_succeeded",
            "git_commit_accepted",
            "provider",
            "provider_id",
            "model",
            "model_id",
            "backend_id",
            "route_id",
            "reasoning_effort",
        }
        if forbidden_claims.intersection(self.result):
            raise ValueError(
                "agent workspace result contains a forbidden commit or route claim"
            )
        manifest = self.result.get("workspace_manifest")
        if isinstance(manifest, Mapping) and manifest.get("proposed_only") is not True:
            raise ValueError("workspace manifest must remain proposed_only")


def execute_agent_workspace_candidate(
    *,
    instruction: str,
    workspace_contract: Mapping[str, Any],
    execution_port: DomainExecutionPort,
) -> AgentWorkspaceResultCandidate:
    contract = AgentWorkspaceExecutionContract.from_mapping(workspace_contract)
    candidate = execute_domain_candidate(
        capability="agent.workspace.execute",
        operation="analyze",
        candidate_kind=CandidateKind.AGENT_RESULT,
        prompt=instruction,
        context={
            "workspace_contract": contract.to_dict(),
            "workspace_contract_hash": contract.contract_hash,
            "commit_authority": "domain_authority_only",
        },
        execution_port=execution_port,
    )
    raw = dict(candidate.raw_output)
    result_kind = AgentResultKind(str(raw.get("result_kind") or ""))
    return AgentWorkspaceResultCandidate(
        result_kind=result_kind,
        result=raw,
        evidence=candidate.evidence,
    )


__all__ = [
    "AgentResultKind",
    "AgentWorkspaceResultCandidate",
    "execute_agent_workspace_candidate",
]
