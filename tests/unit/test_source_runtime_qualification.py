"""TEST: Exact Source qualification scope; these dictionaries are protocol fixtures."""
from copy import deepcopy

import pytest

from novel_forge.modules.command_kernel.errors import KernelError


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
