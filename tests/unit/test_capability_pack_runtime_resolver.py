from __future__ import annotations

import json

import pytest

from novel_forge.modules.capability_pack_authority.domain import (
    CapabilityPackScope,
    ScopeType,
)
from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackResolutionRequest,
    CapabilityPackRuntimeResolver,
)
from novel_forge.modules.command_kernel.errors import KernelError


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
RELEASE_SHA = "c" * 40


def _approval_scope() -> dict[str, object]:
    return {
        "schema_version": "CapabilityPackApprovalScope.v1",
        "allowed_environments": ["validation"],
        "allowed_runtime_profiles": ["validation"],
        "allowed_release_channels": ["VALIDATION"],
        "allowed_scope_types": ["SYSTEM", "PROJECT", "WORKSPACE", "BOOK"],
        "allowed_project_ids": ["project-1"],
        "allowed_workspace_ids": ["workspace-1"],
        "allowed_book_ids": ["book-1"],
        "allowed_workflow_definition_refs": ["chapter_authority_slice@2.3.1"],
        "allow_canary": True,
        "allow_percentage_rollout": True,
        "allow_full_rollout": True,
        "maximum_rollout_percentage": 100,
    }


class _Definitions:
    def get(self, name: str, version: str):
        assert (name, version) == ("chapter.draft.generate", "2.2.0")
        return {"definition_hash": HASH_A, "enabled": True}


class _Packs:
    def __init__(self, candidates, deployments, rollout=None, assignment=None):
        self.candidates = candidates
        self.deployments = deployments
        self.rollout = rollout
        self.assignment = assignment
        self.assigned_subject = ""

    def validate_resolution_scope(self, **_kwargs):
        return None

    def resolve_activation_candidates(self, **_kwargs):
        return list(self.candidates)

    def require_deployment(self, deployment_id: str):
        return dict(self.deployments[deployment_id])

    def active_rollout_for_baseline(self, _deployment_id: str):
        return self.rollout

    def assign_rollout_subject(self, _rollout, _subject_key: str):
        self.assigned_subject = _subject_key
        return dict(self.assignment)

    def latest_approval(self, _compilation_id: str):
        return {
            "decision": "APPROVED",
            "compilation_hash": HASH_B,
            "expires_at": None,
            "approval_scope": _approval_scope(),
            "structured_limitations": [],
        }

    def latest_deprecation(self, _pack_id: str, _pack_version: str):
        return None

    def blocked_dependencies(self, _pack_id: str, _pack_version: str):
        return []


class _AgentRuntime:
    def lock_definition_version(self, agent_id: str, definition_version: int):
        assert (agent_id, definition_version) == ("chapter-draft-agent", 1)
        return {
            "definition_version": 1,
            "definition_hash": HASH_B,
            "capability_pack_ref": "chapter_generation_pack@1.1.0",
            "prompt_bundle_ref": "prompt@1",
            "prompt_bundle_hash": HASH_A,
            "skill_bundle_ref": "skill@1",
            "skill_bundle_hash": HASH_B,
            "tool_policy_ref": "tools@1",
            "tool_policy_hash": HASH_A,
            "context_policy_ref": "context@1",
            "context_policy_hash": HASH_B,
            "capabilities": [
                {
                    "capability_id": "prose.chapter.draft",
                    "capability_version": 1,
                    "capability_hash": HASH_A,
                    "execution_capability_id": "prose.chapter.draft",
                    "execution_capability_hash": HASH_B,
                }
            ],
        }


class _Repositories:
    def __init__(self, packs):
        self.capability_packs = packs
        self.definitions = _Definitions()
        self.agent_runtime = _AgentRuntime()


class _Uow:
    def __init__(self, packs):
        self.repositories = _Repositories(packs)


def _deployment(deployment_id: str):
    return {
        "deployment_id": deployment_id,
        "pack_id": "chapter_generation_pack",
        "pack_version": "1.1.0",
        "compilation_id": "compilation-1",
        "compilation_hash": HASH_B,
        "manifest_hash": HASH_A,
        "catalog_snapshot_hash": HASH_A,
        "binding_set_id": "binding-set-1",
        "binding_set_hash": HASH_B,
        "target_scope_type": "BOOK",
        "deployment_status": "ACTIVE",
        "release_sha": RELEASE_SHA,
        "runtime_profile": "validation",
        "release_channel": "VALIDATION",
        "workflow_definition_ref": "chapter_authority_slice@2.3.1",
        "node_bindings": [
            {
                "workflow_node_id": "draft",
                "operation_definition_ref": "chapter.draft.generate@2.3.1",
                "operation_definition_hash": HASH_A,
                "agent_definition_ref": "chapter-draft-agent@1",
                "agent_definition_hash": HASH_B,
                "capability_ref": "prose.chapter.draft@1",
                "capability_hash": HASH_A,
                "execution_capability_id": "prose.chapter.draft",
                "execution_capability_hash": HASH_B,
                "prompt_bundle_ref": "prompt@1",
                "prompt_bundle_hash": HASH_A,
                "skill_bundle_ref": "skill@1",
                "skill_bundle_hash": HASH_B,
                "tool_policy_ref": "tools@1",
                "tool_policy_hash": HASH_A,
                "context_policy_ref": "context@1",
                "context_policy_hash": HASH_B,
                "evaluation_policy_ref": "evaluation@1",
                "evaluation_policy_hash": HASH_A,
                "route_policy_ref": "route@1",
                "route_policy_hash": HASH_B,
                "approval_policy_ref": "approval@1",
                "approval_policy_hash": HASH_A,
                "budget_policy_ref": "budget@1",
                "budget_policy_hash": HASH_B,
                "input_contract_ref": "schema:draft-input@1",
                "output_contract_ref": "schema:draft-candidate@1",
                "domain_acceptance_policy_ref": "acceptance:draft@1",
                "commit_authority": "CHAPTER_AUTHORITY",
                "prompt_system_instruction_ref": "prompt@1",
                "prompt_system_instruction_hash": HASH_A,
                "prompt_template_ref": "template@1",
                "prompt_template_hash": HASH_B,
                "prompt_compiler_version": "compiler@1",
                "skill_ref": "skill",
                "skill_version": "skill@1",
                "skill_content_hash": HASH_B,
                "context_policy_payload": {"policy_id": "context@1"},
                "tool_policy_payload": {"policy_id": "tools@1"},
                "evaluation_policy_payload": {"policy_id": "evaluation@1"},
            }
        ],
    }


def _request(*, workspace_id: str = "workspace-1", book_id: str = "book-1"):
    return CapabilityPackResolutionRequest(
        project_id="project-1",
        workspace_id=workspace_id,
        book_id=book_id,
        workflow_definition_ref="chapter_authority_slice@2.3.1",
        workflow_node_id="draft",
        environment="validation",
        runtime_profile="validation",
        release_channel="VALIDATION",
        release_sha=RELEASE_SHA,
        operation_definition_ref="chapter.draft.generate@2.3.1",
        pack_id="chapter_generation_pack",
    )


def test_resolver_uses_book_before_workspace_project_and_system() -> None:
    scopes = {
        kind: CapabilityPackScope(
            kind,
            project_id="project-1" if kind is not ScopeType.SYSTEM else "",
            workspace_id=(
                "workspace-1"
                if kind in {ScopeType.WORKSPACE, ScopeType.BOOK}
                else ""
            ),
            book_id="book-1" if kind is ScopeType.BOOK else "",
        )
        for kind in ScopeType
    }
    candidates = [
        {
            "scope_key": scopes[ScopeType.PROJECT].scope_key,
            "target_scope_type": "PROJECT",
            "active_deployment_id": "project-deployment",
            "activation_version": 2,
        },
        {
            "scope_key": scopes[ScopeType.BOOK].scope_key,
            "target_scope_type": "BOOK",
            "active_deployment_id": "book-deployment",
            "activation_version": 4,
        },
    ]
    packs = _Packs(
        candidates,
        {
            "project-deployment": _deployment("project-deployment"),
            "book-deployment": _deployment("book-deployment"),
        },
    )
    snapshot = CapabilityPackRuntimeResolver.resolve_in_uow(_Uow(packs), _request())

    assert snapshot.deployment_id == "book-deployment"
    assert snapshot.activation_version == 4
    assert snapshot.selected_scope_type is ScopeType.BOOK
    assert snapshot.selection_reason == "BOOK deployment selected"


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        (
            (ScopeType.SYSTEM, ScopeType.PROJECT, ScopeType.WORKSPACE, ScopeType.BOOK),
            ScopeType.BOOK,
        ),
        (
            (ScopeType.SYSTEM, ScopeType.PROJECT, ScopeType.WORKSPACE),
            ScopeType.WORKSPACE,
        ),
        ((ScopeType.SYSTEM, ScopeType.PROJECT), ScopeType.PROJECT),
        ((ScopeType.SYSTEM,), ScopeType.SYSTEM),
    ],
)
def test_resolver_proves_full_scope_precedence(
    available: tuple[ScopeType, ...], expected: ScopeType
) -> None:
    scopes = {
        kind: CapabilityPackScope(
            kind,
            project_id="project-1" if kind is not ScopeType.SYSTEM else "",
            workspace_id=(
                "workspace-1"
                if kind in {ScopeType.WORKSPACE, ScopeType.BOOK}
                else ""
            ),
            book_id="book-1" if kind is ScopeType.BOOK else "",
        )
        for kind in ScopeType
    }
    candidates = [
        {
            "scope_key": scopes[kind].scope_key,
            "target_scope_type": kind.value,
            "active_deployment_id": f"{kind.value.lower()}-deployment",
            "activation_version": 1,
        }
        for kind in available
    ]
    deployments = {
        f"{kind.value.lower()}-deployment": _deployment(
            f"{kind.value.lower()}-deployment"
        )
        for kind in available
    }

    snapshot = CapabilityPackRuntimeResolver.resolve_in_uow(
        _Uow(_Packs(candidates, deployments)), _request()
    )

    assert snapshot.selected_scope_type is expected


@pytest.mark.parametrize(
    ("workspace_id", "available", "expected"),
    [
        ("workspace-1", (ScopeType.WORKSPACE, ScopeType.PROJECT), ScopeType.WORKSPACE),
        ("", (ScopeType.PROJECT, ScopeType.SYSTEM), ScopeType.PROJECT),
        ("", (ScopeType.SYSTEM,), ScopeType.SYSTEM),
    ],
)
def test_resolver_omits_unavailable_book_and_workspace_scopes(
    workspace_id: str,
    available: tuple[ScopeType, ...],
    expected: ScopeType,
) -> None:
    scopes = {
        kind: CapabilityPackScope(
            kind,
            project_id="project-1" if kind is not ScopeType.SYSTEM else "",
            workspace_id="workspace-1" if kind is ScopeType.WORKSPACE else "",
        )
        for kind in available
    }
    candidates = [
        {
            "scope_key": scopes[kind].scope_key,
            "target_scope_type": kind.value,
            "active_deployment_id": f"{kind.value.lower()}-deployment",
            "activation_version": 1,
        }
        for kind in available
    ]
    deployments = {
        f"{kind.value.lower()}-deployment": _deployment(
            f"{kind.value.lower()}-deployment"
        )
        for kind in available
    }

    snapshot = CapabilityPackRuntimeResolver.resolve_in_uow(
        _Uow(_Packs(candidates, deployments)),
        _request(workspace_id=workspace_id, book_id=""),
    )

    assert snapshot.selected_scope_type is expected


def test_resolver_freezes_stable_canary_assignment() -> None:
    scope = CapabilityPackScope(
        ScopeType.BOOK,
        project_id="project-1",
        workspace_id="workspace-1",
        book_id="book-1",
    )
    packs = _Packs(
        [
            {
                "scope_key": scope.scope_key,
                "target_scope_type": "BOOK",
                "active_deployment_id": "baseline",
                "activation_version": 1,
            }
        ],
        {"baseline": _deployment("baseline"), "candidate": _deployment("candidate")},
        rollout={
            "rollout_id": "rollout-1",
            "baseline_deployment_id": "baseline",
            "candidate_deployment_id": "candidate",
            "status": "PERCENTAGE",
            "percentage": 50,
            "assignment_key_policy": "BOOK",
        },
        assignment={
            "assignment_id": "assignment-1",
            "selected_deployment_id": "candidate",
            "bucket": 100,
            "assignment_hash": HASH_A,
        },
    )
    snapshot = CapabilityPackRuntimeResolver.resolve_in_uow(_Uow(packs), _request())
    assert snapshot.deployment_id == "candidate"
    assert snapshot.rollout_id == "rollout-1"
    assert snapshot.assignment_ref == "assignment-1"


def test_paused_rollout_fails_back_to_baseline_without_reassigning_subject() -> None:
    scope = CapabilityPackScope(
        ScopeType.BOOK,
        project_id="project-1",
        workspace_id="workspace-1",
        book_id="book-1",
    )
    packs = _Packs(
        [
            {
                "scope_key": scope.scope_key,
                "target_scope_type": "BOOK",
                "active_deployment_id": "baseline",
                "activation_version": 1,
            }
        ],
        {"baseline": _deployment("baseline"), "candidate": _deployment("candidate")},
        rollout={
            "rollout_id": "rollout-1",
            "baseline_deployment_id": "baseline",
            "candidate_deployment_id": "candidate",
            "status": "PAUSED",
            "percentage": 50,
            "assignment_key_policy": "BOOK",
        },
        assignment=None,
    )

    snapshot = CapabilityPackRuntimeResolver.resolve_in_uow(_Uow(packs), _request())

    assert snapshot.deployment_id == "baseline"
    assert snapshot.assignment_ref == "rollout:rollout-1:paused-baseline"


def test_completed_rollout_obeys_promoted_activation_pointer() -> None:
    scope = CapabilityPackScope(
        ScopeType.BOOK,
        project_id="project-1",
        workspace_id="workspace-1",
        book_id="book-1",
    )
    packs = _Packs(
        [
            {
                "scope_key": scope.scope_key,
                "target_scope_type": "BOOK",
                "active_deployment_id": "candidate",
                "activation_version": 2,
            }
        ],
        {"baseline": _deployment("baseline"), "candidate": _deployment("candidate")},
        rollout=None,
    )

    snapshot = CapabilityPackRuntimeResolver.resolve_in_uow(_Uow(packs), _request())

    assert snapshot.deployment_id == "candidate"
    assert snapshot.activation_version == 2
    assert snapshot.rollout_id == ""
    assert snapshot.assignment_ref.endswith("@2")


def test_project_workspace_rollout_policy_does_not_bucket_by_book() -> None:
    scope = CapabilityPackScope(
        ScopeType.WORKSPACE,
        project_id="project-1",
        workspace_id="workspace-1",
    )
    packs = _Packs(
        [
            {
                "scope_key": scope.scope_key,
                "target_scope_type": "WORKSPACE",
                "active_deployment_id": "baseline",
                "activation_version": 1,
            }
        ],
        {"baseline": _deployment("baseline"), "candidate": _deployment("candidate")},
        rollout={
            "rollout_id": "rollout-1",
            "baseline_deployment_id": "baseline",
            "candidate_deployment_id": "candidate",
            "status": "PERCENTAGE",
            "percentage": 50,
            "assignment_key_policy": "PROJECT_WORKSPACE",
        },
        assignment={
            "assignment_id": "assignment-1",
            "selected_deployment_id": "baseline",
            "bucket": 100,
            "assignment_hash": HASH_A,
        },
    )

    CapabilityPackRuntimeResolver.resolve_in_uow(
        _Uow(packs), _request(book_id="")
    )

    assert packs.assigned_subject == "project-1:workspace-1"


def test_resolver_fails_closed_on_operation_definition_drift() -> None:
    scope = CapabilityPackScope(
        ScopeType.BOOK,
        project_id="project-1",
        workspace_id="workspace-1",
        book_id="book-1",
    )
    deployment = _deployment("deployment-1")
    deployment["node_bindings"][0]["operation_definition_hash"] = HASH_B
    packs = _Packs(
        [
            {
                "scope_key": scope.scope_key,
                "target_scope_type": "BOOK",
                "active_deployment_id": "deployment-1",
                "activation_version": 1,
            }
        ],
        {"deployment-1": deployment},
    )
    with pytest.raises(KernelError) as raised:
        CapabilityPackRuntimeResolver.resolve_in_uow(_Uow(packs), _request())
    assert raised.value.code == "CAPABILITY_PACK_OPERATION_DEFINITION_DRIFT"


def test_runtime_admission_validates_pack_driven_derived_pep_contract() -> None:
    scope = CapabilityPackScope(
        ScopeType.BOOK,
        project_id="project-1",
        workspace_id="workspace-1",
        book_id="book-1",
    )
    packs = _Packs(
        [
            {
                "scope_key": scope.scope_key,
                "target_scope_type": "BOOK",
                "active_deployment_id": "deployment-1",
                "activation_version": 1,
            }
        ],
        {"deployment-1": _deployment("deployment-1")},
    )
    snapshot = CapabilityPackRuntimeResolver.resolve_in_uow(_Uow(packs), _request())
    assert json.loads(snapshot.context_policy_payload_json) == {
        "policy_id": "context@1"
    }
    assert json.loads(snapshot.evaluation_policy_payload_json) == {
        "policy_id": "evaluation@1"
    }
    contract = {
        "operation_definition_ref": snapshot.operation_definition_ref,
        "operation_definition_hash": snapshot.operation_definition_hash,
        "agent_definition_ref": snapshot.agent_definition_ref,
        "agent_definition_hash": snapshot.agent_definition_hash,
        "capability_ref": snapshot.capability_ref,
        "capability_hash": snapshot.capability_hash,
        "execution_capability_id": snapshot.execution_capability_id,
        "execution_capability_hash": snapshot.execution_capability_hash,
        "tool_policy_ref": snapshot.tool_policy_ref,
        "tool_policy_hash": snapshot.tool_policy_hash,
        "context_policy_ref": snapshot.context_policy_ref,
        "context_policy_hash": snapshot.context_policy_hash,
        "evaluation_policy_ref": snapshot.evaluation_policy_ref,
        "evaluation_policy_hash": snapshot.evaluation_policy_hash,
        "release_sha": snapshot.release_sha,
        "derived_execution_contract": True,
        "prompt_system_instruction_hash": HASH_A,
        "prompt_template_hash": HASH_B,
        "prompt_compiler_version": "compiler@1",
        "skill_ref": "skill@1",
        "skill_content_hash": HASH_B,
        "governing_tool_policy_ref": "tools@1",
        "governing_tool_policy_hash": HASH_A,
        "governing_context_policy_ref": "context@1",
        "governing_context_policy_hash": HASH_B,
        "governing_evaluation_policy_ref": "evaluation@1",
        "governing_evaluation_policy_hash": HASH_A,
    }

    CapabilityPackRuntimeResolver.validate_runtime_admission(snapshot, contract)
    contract["prompt_template_hash"] = HASH_A
    with pytest.raises(KernelError) as raised:
        CapabilityPackRuntimeResolver.validate_runtime_admission(snapshot, contract)
    assert raised.value.code == "CAPABILITY_PACK_DERIVED_CONTRACT_DRIFT"
