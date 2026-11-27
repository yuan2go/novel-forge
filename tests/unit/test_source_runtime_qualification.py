"""TEST: Exact Source qualification scope; these dictionaries are protocol fixtures."""
from copy import deepcopy

import pytest

from novel_forge.modules.command_kernel.errors import KernelError


def test_settled_source_qualification_preserves_original_release(monkeypatch):
    from scripts.source_qualification import qualification_release
    from novel_forge.tools import implementation_tree_identity
    monkeypatch.setattr(implementation_tree_identity, "build_git_implementation_tree_identity",
                        lambda root, sha: {"implementation_tree_sha": "original-tree:" + sha})
    identity = {"route": {"release_sha": "a" * 40}}
    result = qualification_release(identity, scope={"status": "SUCCEEDED"}, root="unused",
                                   commit_sha="b" * 40, implementation_identity="current-tree")
    assert result == ("a" * 40, "original-tree:" + "a" * 40)
    with pytest.raises(ValueError, match="settled original Source"):
        qualification_release(identity, scope={"status": "READY"}, root="unused",
                              commit_sha="b" * 40, implementation_identity="current-tree")
    assert qualification_release(identity, scope={"status": "READY"}, root="unused",
                                 commit_sha="a" * 40, implementation_identity="same-tree") == ("a" * 40, "same-tree")



def provider_receipt(capability="mkaos.knowledge.extract"):
    route = {key: key + ":fixture" for key in (
        "backend_id", "backend_version", "runtime_host_id", "auth_profile_ref", "model_profile_id",
        "model_profile_hash", "model_provider", "model_id", "policy_id", "route_policy_hash",
        "output_schema_ref", "release_sha", "reasoning_effort",
    )}
    route.update(model_profile_version=1, policy_version=1)
    execution_id = "source-execution:fixture"
    return {
        "fixture_protocol_only": False, "real_model_call": True,
        "provider_id": route["model_provider"], "model_id": route["model_id"],
        "result": {"fixture": "candidate"},
        "usage": {"total_tokens": 4}, "cost": {"amount": "0.1", "currency": "USD"},
        "capability_runtime": {"system_instruction": {"content_hash": "instruction"},
                               "prompt_template": {"content_hash": "prompt"},
                               "skill": {"content_hash": "skill"},
                               "output_schema_hash": "schema"},
        "production_execution": {
            "execution_request": {"execution_id": execution_id, "external_effect_id": "effect", "capability": capability},
            "execution_handle": {"execution_id": execution_id, "backend_id": route["backend_id"], "transport": "REMOTE_PROVIDER_API", "provider_request_id": "provider-request"},
            "execution_result": {"execution_id": execution_id, "outcome": "SUCCEEDED", "normalized_output_ref": "output", "usage_receipt_ref": "usage", "cost_receipt_ref": "cost"},
            "route_snapshot": route,
        },
    }


def test_d0_retrieval_or_mismatched_runtime_cannot_qualify_source():
    from novel_forge.modules.provider_qualification.source_binding import source_runtime_identity
    source = provider_receipt()
    identity = source_runtime_identity(source)
    assert identity["capability"] == "mkaos.knowledge.extract"
    for changed in ("auth_profile_ref", "model_id", "model_profile_hash", "backend_version", "release_sha", "runtime_host_id"):
        other = deepcopy(source)
        other["production_execution"]["route_snapshot"][changed] += ":different"
        if changed == "model_id":
            other["model_id"] = other["production_execution"]["route_snapshot"][changed]
        assert source_runtime_identity(other) != identity
    with pytest.raises(KernelError, match="SOURCE_RUNTIME_QUALIFICATION"):
        source_runtime_identity(provider_receipt("model.retrieval"))
    for changed in ("fixture", "unknown", "receipt"):
        invalid = deepcopy(source)
        if changed == "fixture":
            invalid["fixture_protocol_only"] = True
        elif changed == "unknown":
            invalid["production_execution"]["execution_result"]["outcome"] = "UNKNOWN"
        else:
            invalid["production_execution"]["execution_result"].pop("usage_receipt_ref")
        with pytest.raises(KernelError, match="SOURCE_RUNTIME_QUALIFICATION"):
            source_runtime_identity(invalid)


def test_non_reasoning_route_is_preserved_and_revoked_qualification_blocks_context():
    from novel_forge.modules.provider_qualification.source_binding import source_runtime_identity
    from novel_forge.modules.mkaos_authority.query import _context_eligible_card
    evidence = provider_receipt()
    evidence["production_execution"]["route_snapshot"]["reasoning_effort"] = "none"
    assert source_runtime_identity(evidence)["route"]["reasoning_effort"] == "none"
    card = {"runtime_qualification_current": True, "content": {"source_policy": {
        "knowledge_card_context_eligible": True, "raw_source_expression_included": False,
        "source_chunks_direct_context_eligible": False, "fixture_protocol_only": False,
        "approval_class": "PRODUCTION", "production_context_eligible": True}}}
    assert _context_eligible_card(card, {"usage_scope": "PRODUCTION"})
    card["runtime_qualification_current"] = False
    assert not _context_eligible_card(card, {"usage_scope": "PRODUCTION"})


def entitlement_cost():
    from novel_forge.modules.production_execution.backends import CodexAccountEntitlementSnapshot
    snapshot = CodexAccountEntitlementSnapshot(
        authorization_ref="authorization:source-bounded-fixture",
        account_identity_ref="account:source-fixture", cli_version="fixture-cli-v1",
        executable_sha256="sha256:" + "a" * 64, configuration_ref="config:source-fixture",
    )
    return {"availability": "UNAVAILABLE", "measurement": "UNKNOWN", "model": "fixture-model",
            "currency": "UNKNOWN", "accounting_basis": "ACCOUNT_ENTITLEMENT",
            "reason": "monetary_cost_not_observable", "authorization_ref": snapshot.authorization_ref,
            "entitlement_snapshot_hash": snapshot.snapshot_hash,
            "entitlement_snapshot": snapshot.to_dict(), "provider_billed": "UNKNOWN"}


def live_payload(cost):
    return {
        "schema_version": "d0-live-qualification-evidence.v1", "release_sha": "a" * 40,
        "implementation_identity": "sha256:" + "b" * 64, "source_operation_id": "source:fixture",
        "external_effect_id": "effect:fixture", "request_object_ref": "s3://fixture/request",
        "response_object_ref": "s3://fixture/response", "auth_profile_ref": "auth:fixture",
        "provider": "codex-cli", "backend_id": "codex-cli", "model": "fixture-model",
        "model_version": "fixture-model", "route_snapshot_id": "route:fixture",
        "route_snapshot_hash": "sha256:" + "c" * 64, "prompt_version": "prompt:v1",
        "prompt_hash": "sha256:" + "d" * 64, "instruction_version": "instruction:v1",
        "instruction_hash": "sha256:" + "e" * 64, "skill_version": "skill:v1",
        "skill_hash": "sha256:" + "f" * 64, "request_hash": "sha256:" + "1" * 64,
        "response_hash": "sha256:" + "2" * 64, "provider_execution_id": "execution:fixture",
        "provider_request_identity": "receipt:fixture",
        "usage": {"measurement": "MEASURED", "input_tokens": 11, "output_tokens": 3, "total_tokens": 14},
        "cost": cost, "latency": {"duration_ms": 42},
        "controlled_failure": {"checkpoint": "after_provider_response_before_effect_receipt", "failure_kind": "response_loss", "request_sent": True},
        "recovery": {"external_state_was_ambiguous": True, "recovered_without_resend": True, "replayed": True},
        "fixture_protocol_only": False, "real_model_call": True,
    }


def test_source_runtime_identity_binds_entitlement_account_and_never_invents_price():
    from novel_forge.modules.provider_qualification.source_binding import source_runtime_identity
    evidence = provider_receipt()
    evidence["cost"] = entitlement_cost()
    evidence["cost"]["model"] = evidence["model_id"]
    identity = source_runtime_identity(evidence)
    assert identity["accounting_scope"]["account_identity_ref"] == "account:source-fixture"
    assert identity["accounting_scope"]["authorization_ref"] == "authorization:source-bounded-fixture"
    assert "amount" not in evidence["cost"]
    invalid = deepcopy(evidence)
    invalid["cost"]["entitlement_snapshot"]["account_identity_ref"] = "another-account"
    with pytest.raises(KernelError, match="SOURCE_RUNTIME_QUALIFICATION_REQUIRED"):
        source_runtime_identity(invalid)


def test_d0_entitlement_cost_unknown_is_valid_but_usage_unknown_and_fake_price_are_not():
    from novel_forge.modules.provider_qualification import D0LiveQualificationEvidence
    payload = live_payload(entitlement_cost())
    evidence = D0LiveQualificationEvidence.from_mapping(payload)
    assert evidence.cost["measurement"] == "UNKNOWN"
    assert "amount" not in evidence.cost
    for cost in ({**entitlement_cost(), "amount": "0"},
                 {**entitlement_cost(), "pricing_snapshot_hash": "sha256:" + "4" * 64},
                 {**entitlement_cost(), "authorization_ref": "different-authorization"}):
        with pytest.raises(ValueError, match="entitlement"):
            D0LiveQualificationEvidence.from_mapping(live_payload(cost))
    with pytest.raises(ValueError, match="measured Provider usage"):
        D0LiveQualificationEvidence.from_mapping({**payload, "usage": {"availability": "UNAVAILABLE", "measurement": "UNKNOWN"}})


def test_source_qualification_entitlement_preview_requires_authorization_without_dispatch(monkeypatch):
    from types import SimpleNamespace
    from scripts import source_qualification
    monkeypatch.setattr(source_qualification, "inspect_source_operation", lambda *args, **kwargs: {"status": "READY"})
    monkeypatch.setenv("NOVEL_FORGE_CODEX_ACCOUNTING_MODE", "ACCOUNT_ENTITLEMENT")
    result = source_qualification.run_source_qualification(
        SimpleNamespace(database_url="unused", source_project_id="p", source_operation_id="op",
                        source_capability="mkaos.knowledge.extract", execute=False),
        root=None, commit_sha="a" * 40, implementation_identity="sha256:" + "b" * 64,
    )
    assert result["status"] == "READY_FOR_AUTHORIZATION"
    assert result["required_route_contract"]["accounting_basis"] == "ACCOUNT_ENTITLEMENT"
    assert result["required_route_contract"]["monetary_cost"] == "UNKNOWN"
    assert result["required_route_contract"]["finite_project_call_and_token_limits_required"] is True
    assert result["provider_request_sent"] is False


@pytest.mark.parametrize("change", ["", "unknown", "authorization", "legacy", "mixed_caps", "usage"])
def test_current_membership_qualification_preserves_settlement_without_cumulative_caps(change):
    from novel_forge.modules.provider_qualification.accounting import require_entitlement_budget
    cost = entitlement_cost()
    evidence = {"cost_authorization_ref": cost["authorization_ref"], "resource_control_version": "billing-channel-resources.v1",
        "call_caps": {}, "token_caps": {}}
    row = ["reservation", "SETTLED", "ACCOUNT_ENTITLEMENT", "UNKNOWN", None, None, None, "UNKNOWN", "UNKNOWN", 100, 180, evidence]
    usage = {"total_tokens": 180}
    if change == "unknown":
        row[1] = "HELD_UNKNOWN"
    elif change == "authorization":
        evidence["cost_authorization_ref"] = "foreign"
    elif change == "legacy":
        evidence.pop("resource_control_version")
    elif change == "mixed_caps":
        evidence["call_caps"] = {"project_total": 1}
    elif change == "usage":
        usage["total_tokens"] = None
    if change:
        with pytest.raises(ValueError):
            require_entitlement_budget(None, project_id="project", effect_id="effect", cost=cost, usage=usage, reservation_rows=[tuple(row)])
    else:
        result = require_entitlement_budget(None, project_id="project", effect_id="effect", cost=cost, usage=usage, reservation_rows=[tuple(row)])
        assert result["call_caps"] == result["token_caps"] == {}
        assert result["resource_control_version"] == "billing-channel-resources.v1"
        assert result["estimated_tokens"] == 100 and result["actual_tokens"] == 180
        assert result["monetary_cost"] == "UNKNOWN"
