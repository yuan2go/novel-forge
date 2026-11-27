from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.authority_handler_runtime.policy_commands import owned_policy_definition
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.routing_policy import validate_routing_policy
from novel_forge.modules.production_execution.routing_sources import matching_bindings, require_source_permissions
from tests.unit.test_cost_aware_routing import candidate


def export_scope():
    model = candidate(model_revision="model-revision:v1")
    return {"contract_version": "routing-benchmark-export.v1", "export_id": "export:one",
        "source_project_id": "source", "target_project_id": "target", "target_work_id": "book:target",
        "task_type": "draft", "candidate_id": model.candidate_id, "provider": model.provider,
        "model": model.model, "reasoning": model.reasoning, "model_revision": model.model_revision,
        "producer_contract_hash": "sha256:" + "a" * 64, "campaign_id": "campaign:one", "manifest_hash": "sha256:" + "b" * 64,
        "campaign_expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), "reason": "bounded native test only",
        "observations": [{"asset_version_id": "observation:one", "content_hash": "sha256:" + "c" * 64}]}


def policy(row=None):
    return {"policy_version": "v1", "reason": "test", "task_overrides": [], "benchmark_exports": [row or export_scope()]}


def test_exact_export_policy_and_new_definition_leave_legacy_contract_unchanged():
    current = policy()
    validate_routing_policy(current)
    legacy = {key: value for key, value in current.items() if key != "benchmark_exports"}
    args = dict(owner="PROVIDER_ROUTING", application_build_id="test", commit_sha="e" * 40)
    old = owned_policy_definition(content=legacy, **args)
    new = owned_policy_definition(content=current, **args)
    assert old["definition_version"] == "1.2.0" and new["definition_version"] == "1.3.0"
    assert "benchmark_exports" not in old["command_schema"]["properties"]["policy"]["properties"]
    assert new["command_schema_version"].endswith(".v3")


@pytest.mark.parametrize("mutation", [
    lambda row: row.update(target_project_id="source"),
    lambda row: row.update(expires_at="2026-10-01T12:00:00"),
    lambda row: row.update(observations=row["observations"] * 2),
    lambda row: row.update(producer_contract_hash="latest"),
    lambda row: row.update(observations=[]),
    lambda row: row.update(model_revision=""),
    lambda row: row.update(approval_ref="arbitrary-unowned-string"),
])
def test_export_contract_rejects_unbounded_or_unowned_source(mutation):
    row = export_scope()
    mutation(row)
    with pytest.raises(KernelError, match="ROUTING_POLICY_SCHEMA_INVALID"):
        validate_routing_policy(policy(row))


def test_export_and_import_both_require_cross_project_operator_scope():
    actor = Principal("operator", PrincipalType.LOCAL_OPERATOR, frozenset({"book.authority.execute"}), frozenset({"source"}), "test")
    with pytest.raises(PermissionError):
        require_source_permissions(actor, project_id="source", content=policy())
    current = {"benchmark_source_bindings": [{"export": export_scope()}]}
    with pytest.raises(PermissionError):
        require_source_permissions(replace(actor, project_scope=frozenset({"target"})), project_id="target", content=current)
    authorized = replace(actor, project_scope=frozenset({"source", "target"}))
    require_source_permissions(authorized, project_id="source", content=policy())
    require_source_permissions(authorized, project_id="target", content=current)


@pytest.mark.parametrize("field,value", [("project_id", "other"), ("work_id", "other"), ("task_type", "review"), ("producer_contract_hash", "sha256:" + "d" * 64)])
def test_export_match_is_task_book_producer_scoped(field, value):
    row = export_scope()
    args = dict(project_id="target", work_id="book:target", task_type="draft", candidate=candidate(model_revision="model-revision:v1"), producer_contract_hash=row["producer_contract_hash"])
    content = {"benchmark_source_bindings": [{"export": row}]}
    assert matching_bindings(content, **args) == content["benchmark_source_bindings"]
    assert matching_bindings(content, **{**args, field: value}) == []
    assert matching_bindings(content, **{**args, "candidate": replace(args["candidate"], model_revision="different")}) == []


def test_duplicate_binding_identity_is_not_an_extra_sample():
    scope = export_scope()
    binding = {"export": scope, "source_policy": {"policy_version": "v1", "content_hash": "d" * 64, "operation_id": "operation:one"}}
    with pytest.raises(KernelError, match="ROUTING_POLICY_SCHEMA_INVALID"):
        validate_routing_policy({"policy_version": "target-v1", "reason": "test", "task_overrides": [], "benchmark_source_bindings": [binding, deepcopy(binding)]})


def test_matched_exports_cannot_silently_exceed_native_read_limit():
    first = export_scope()
    first["observations"] = [{"asset_version_id": "observation:" + str(number), "content_hash": "sha256:" + "a" * 64} for number in range(200)]
    second = {**deepcopy(first), "export_id": "export:two", "observations": [first["observations"][0]]}
    content = {"benchmark_source_bindings": [{"export": first}, {"export": second}]}
    args = dict(project_id="target", work_id="book:target", task_type="draft", candidate=candidate(model_revision="model-revision:v1"), producer_contract_hash=first["producer_contract_hash"])
    assert len(matching_bindings(content, **args)) == 2
    second["observations"] = [{"asset_version_id": "observation:201", "content_hash": "sha256:" + "b" * 64}]
    with pytest.raises(KernelError, match="ROUTING_BENCHMARK_SOURCE_SCOPE_EXCEEDED"):
        matching_bindings(content, **args)
