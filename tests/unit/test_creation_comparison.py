from copy import deepcopy
from pathlib import Path

import pytest

from novel_forge.storage.versioned_policy_repository import policy_hash

from scripts.creation_comparison import (
    comparison_contract_hash,
    creation_resume_semantics,
    validate_comparison_budget,
    validate_creation_comparison,
)


def comparison_contract():
    return {
        "contract_version": "creative-experiment-budget.v1",
        "experiment_id": "fixture-comparison",
        "accounting_basis": "ACCOUNT_ENTITLEMENT",
        "shared_total": {"calls": 480, "tokens": 12000000},
        "arms": [{
            "arm": name, "project_id": "project-" + name, "book_id": "book-" + name,
            "project_total": {"calls": 270 if name == "A" else 210, "tokens": 6750000 if name == "A" else 5250000},
            "source_allocation": {"calls": 60 if name == "A" else 0, "tokens": 1500000 if name == "A" else 0},
            "creation_allocation": {"calls": 180, "tokens": 4500000},
            "repair_allocation": {"calls": 30, "tokens": 750000},
        } for name in ("A", "B")],
    }


def comparison_identities(tmp_path, *, book_names=("book-A", "book-B"), target_chapters=180):
    contract = comparison_contract()
    for arm, book in zip(contract["arms"], book_names, strict=True):
        arm["book_id"] = book
    identities = []
    for arm in contract["arms"]:
        name = arm["arm"]
        authorization_ref = "fixture:explicit-protocol-only-" + name
        authorization = {"authorization_ref": authorization_ref, "evidence_hash": "sha256:" + "a" * 64,
            "project_id": arm["project_id"], "book_id": arm["book_id"],
            "authorized_cumulative_caps": {phase.upper(): deepcopy(arm[phase + "_allocation"]) for phase in ("source", "creation", "repair")}}
        scope = {
            "project_id": arm["project_id"], "book_id": arm["book_id"],
            "workspace_id": "workspace-" + name, "run_key": "creation-" + name,
            "runtime_root": str((tmp_path / name).resolve()),
            "provider_execution_root": str((tmp_path / name / "executions").resolve()),
        }
        profile = {"model_provider": "scripted_provider_v2", "model_id": "fixture-model", "reasoning_effort": "xhigh", "backend_id": "fixture-only"}
        route = {
            "model_profile": profile, "route_policy": {"policy_id": "fixture-route"},
            "fallback_policy": {"mode": "FAIL_CLOSED"}, "backend_version": "fixture-v1",
            "auth_profile_ref": "fixture-account", "prompt_version": "fixture-prompt-v1",
            "skill_version": "fixture-skill-v1", "system_instruction_hash": "sha256:" + "1" * 64,
            "template_hash": "sha256:" + "2" * 64, "skill_content_hash": "sha256:" + "3" * 64,
            "prompt_compiler_version": "fixture-compiler-v1", "output_schema_ref": "fixture-schema-v1",
            "model_context_limit": 200000, "token_accounting_method": "fixture-count",
            "token_accounting_evidence_ref": "fixture-count-v1", "token_safety_margin": 1000,
            "token_framing_overhead": 100,
        }
        runtime = {
            "NOVEL_FORGE_PROJECT_PROVIDER_CALL_LIMIT": str(arm["project_total"]["calls"]),
            "NOVEL_FORGE_PROJECT_PROVIDER_TOKEN_LIMIT": str(arm["project_total"]["tokens"]),
            "NOVEL_FORGE_CODEX_ACCOUNTING_MODE": "ACCOUNT_ENTITLEMENT",
            "NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF": authorization_ref,
            "NOVEL_FORGE_CODEX_ACCOUNT_IDENTITY_REF": "fixture-account",
            "NOVEL_FORGE_CODEX_CLI_VERSION": "fixture-cli-v1",
            "NOVEL_FORGE_CODEX_EXECUTABLE_SHA256": "a" * 64,
            "NOVEL_FORGE_CODEX_CONFIGURATION_REF": "fixture-input-only-configuration",
            "NOVEL_FORGE_BOOK_CONTEXT_TOKEN_BUDGET": "32000",
            "NOVEL_FORGE_BOOK_QUALITY_CONTEXT_TOKEN_BUDGET": "48000",
            "NOVEL_FORGE_OPERATION_PROVIDER_CALL_LIMIT": "20",
        }
        base = {
            "implementation_identity": "sha256:" + "4" * 64,
            "brief_input_hash": "sha256:" + "5" * 64,
            "formation_policy": {"contract_version": "formation-generation.v1", "target_chapters": target_chapters, "creative_candidates": 2},
        }
        frozen = {
            **deepcopy(base), "contract_version": "creation-pilot.v1", "run_key": scope["run_key"],
            "creation_policy": {
                "contract_version": "creation-input-policy.v1",
                "profiles": {"production_profile": {"content": {"target_chapter_count": target_chapters,
                    "knowledge_access_policy": {"mode": "ALLOW_ONLY" if name == "A" else "DENY_ALL", "allowed_knowledge_card_asset_version_ids": ["approved:v1"] if name == "A" else []}}}},
                "chapter_group_execution": {"maximum_chapters": 3, "preferred_chapters": 3},
                "pilot_stop_after_chapter": 6 if target_chapters > 6 else 0,
                "future_plan_change": {"after_chapter": 3, "directive": "same bounded future change"},
            },
            "models": {"draft": route}, "runtime_settings": runtime, "runtime_identity": scope,
            "cost_accounting": {"accounting_basis": "ACCOUNT_ENTITLEMENT", "authorization_ref": authorization_ref, "authorized_total_usd": None, "monetary_cost_status": "UNKNOWN"},
            "comparison_budget": deepcopy(contract),
            "input_snapshot": {"manifest_file_hash": "sha256:" + "b" * 64, "integrity": "PINNED_MANIFEST_AND_FILES",
                "files": {role: {"name": role + ".json", "content_hash": "sha256:" + "c" * 64} for role in ("brief", "creation", "formation", "budget")}},
        }
        phases = {}
        for phase, calls in {"SOURCE": 10 if name == "A" else 0, "CREATION": 80 if name == "A" else 70, "REPAIR": 2 if name == "A" else 3}.items():
            phases[phase] = {"calls_used_or_reserved": calls, "conservative_tokens": calls * 1000,
                "recorded_actual_tokens": calls * 1000, "unmeasured_reserved_tokens": 0}
        total = {key: sum(phase[key] for phase in phases.values()) for key in phases["SOURCE"]}
        identities.append({
            **base, "project_id": arm["project_id"], "book_id": arm["book_id"], "run_key": scope["run_key"],
            "evidence_class": "FIXTURE_PROTOCOL_ONLY", "frozen_configuration": frozen,
            "budget_binding": {"owner": "CREATIVE_EXPERIMENT_BUDGET", "policy_version": "fixture-v1",
                "policy_hash": policy_hash({"policy_version": "fixture-v1", "comparison_budget": contract, "authorization": authorization}), "contract_hash": comparison_contract_hash(contract), "subject_id": "project:" + arm["project_id"], "authorization": authorization},
            "budget_usage": {"contract_hash": comparison_contract_hash(contract), "project_id": arm["project_id"], "book_id": arm["book_id"],
                "phases": phases, "project_total": total, "shared_total": deepcopy(total),
                "reservation_ids": [f"{name}:fixture-reservation:{n}" for n in range(total["calls_used_or_reserved"])],
                "evidence_class": "POSTGRESQL_BUDGET_LEDGER", "creation_opportunity": {"first_reservation_id": f"{name}:fixture-reservation:0", "policy_hash": policy_hash({"policy_version": "fixture-v1", "comparison_budget": contract, "authorization": authorization}), "authorized_cumulative_caps": deepcopy(authorization["authorized_cumulative_caps"]) }},
        })
    return identities


def test_prior_source_allocation_and_different_actual_consumption_preserve_equal_creative_opportunity(tmp_path):
    left, right = comparison_identities(tmp_path)
    unchanged = deepcopy((left, right))
    result = validate_creation_comparison(left, right)
    assert result["status"] == "COMPARABLE_RECORDED_OPPORTUNITY"
    assert {item["category"] for item in result["classified_differences"]} == {
        "PROJECT_AND_SOURCE_ALLOCATION", "ISOLATED_RUNTIME_IDENTITY", "ACTUAL_LEDGER_USAGE", "AUTHORIZATION_PROVENANCE",
    }
    assert result["real_provider_execution"] == "NOT_ESTABLISHED_BY_COMPARISON"
    assert result["creative_benefit"] == "NOT_PROVEN"
    assert (left, right) == unchanged


@pytest.mark.parametrize("phase", ["creation_allocation", "repair_allocation"])
def test_same_shared_total_cannot_hide_different_creative_phase_opportunities(phase):
    contract = comparison_contract()
    contract["arms"][1][phase]["calls"] -= 1
    contract["arms"][1]["project_total"]["calls"] -= 1
    with pytest.raises(ValueError, match="creative opportunity"):
        validate_comparison_budget(contract, require_both_arms=True)


@pytest.mark.parametrize("mutation,message", [
    (lambda c: c["arms"][1]["source_allocation"].update(calls=1, tokens=1), "control"),
    (lambda c: c["shared_total"].update(calls=479), "shared authorized"),
    (lambda c: c["arms"][0]["project_total"].update(calls=271), "equal its frozen"),
    (lambda c: c["arms"][1].update(project_id=c["arms"][0]["project_id"]), "independent"),
    (lambda c: c["arms"][0]["creation_allocation"].update(calls=True), "finite integer"),
    (lambda c: c["shared_total"].update(tokens=float("inf")), "finite integer"),
    (lambda c: c.update(authorization_ref="a-plan-is-not-a-grant"), "unknown fields"),
    (lambda c: c.update(unclassified_limit=1), "unknown fields"),
])
def test_invalid_budget_plan_is_not_normalized_into_comparability(mutation, message):
    contract = comparison_contract()
    mutation(contract)
    with pytest.raises(ValueError, match=message):
        validate_comparison_budget(contract, require_both_arms=True)


def test_source_only_plan_is_valid_for_preparation_but_cannot_establish_comparison():
    contract = comparison_contract()
    contract["arms"] = contract["arms"][:1]
    assert validate_comparison_budget(contract) == contract
    with pytest.raises(ValueError, match="both A/B"):
        validate_comparison_budget(contract, require_both_arms=True)


def test_native_source_stop_cap_does_not_change_full_creative_opportunity(tmp_path):
    identity = comparison_identities(tmp_path)[0]
    binding = identity["budget_binding"]
    binding["authorization"]["authorized_cumulative_caps"]["SOURCE"] = {"calls": 0, "tokens": 100}
    binding["policy_hash"] = policy_hash({
        "policy_version": binding["policy_version"],
        "comparison_budget": identity["frozen_configuration"]["comparison_budget"],
        "authorization": binding["authorization"],
    })
    assert creation_resume_semantics(identity["frozen_configuration"], binding, require_creation=True)


@pytest.mark.parametrize("mutation,message", [
    (lambda r: r["runtime_settings"].update(NOVEL_FORGE_BOOK_CONTEXT_TOKEN_BUDGET="64000"), "runtime policy"),
    (lambda r: r["runtime_settings"].update(NOVEL_FORGE_OPERATION_PROVIDER_CALL_LIMIT="40"), "budgets"),
    (lambda r: r["runtime_settings"].update(NOVEL_FORGE_PROJECT_PROVIDER_CALL_LIMIT="480"), "arm allocation"),
    (lambda r: r["runtime_settings"].update(NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF="unbound-grant"), "runtime authorization"),
    (lambda r: r["runtime_settings"].update(NOVEL_FORGE_CODEX_ACCOUNT_IDENTITY_REF="another-account"), "runtime policy"),
    (lambda r: r["runtime_settings"].update(NOVEL_FORGE_HIDDEN_CONTEXT_POLICY="same-new-unknown-policy"), "unclassified"),
    (lambda r: r["models"]["draft"].update(template_hash="sha256:" + "9" * 64), "identical frozen model"),
    (lambda r: r["models"]["draft"]["model_profile"].update(model_id="another-model"), "identical frozen model"),
    (lambda r: r["models"]["draft"].pop("skill_content_hash"), "missing or unknown"),
    (lambda r: r["cost_accounting"].update(authorized_total_usd="0"), "invent monetary"),
    (lambda r: r["cost_accounting"].update(authorization_ref="unbound"), "exact budget authorization"),
    (lambda r: r["creation_policy"].update(pilot_stop_after_chapter=9), "word targets"),
    (lambda r: r.pop("comparison_budget"), "missing or unknown"),
])
def test_material_runtime_or_provenance_drift_is_rejected(tmp_path, mutation, message):
    left, right = comparison_identities(tmp_path)
    mutation(right["frozen_configuration"])
    with pytest.raises(ValueError, match=message):
        validate_creation_comparison(left, right)


def test_same_unknown_runtime_setting_in_both_arms_is_still_rejected(tmp_path):
    identities = comparison_identities(tmp_path)
    for identity in identities:
        identity["frozen_configuration"]["runtime_settings"]["NOVEL_FORGE_UNKNOWN_RETRY_POLICY"] = "same"
    with pytest.raises(ValueError, match="unclassified"):
        validate_creation_comparison(*identities)


@pytest.mark.parametrize("fault", ["missing", "unmeasured", "foreign", "incomplete_refs", "shared_refs", "wrong_contract"])
def test_missing_or_ambiguous_native_ledger_evidence_cannot_count_as_zero(tmp_path, fault):
    left, right = comparison_identities(tmp_path)
    usage = right["budget_usage"]
    if fault == "missing":
        del right["budget_usage"]
    elif fault == "unmeasured":
        for values in (usage["phases"]["CREATION"], usage["project_total"]):
            values["recorded_actual_tokens"] -= 1000
            values["unmeasured_reserved_tokens"] += 1000
    elif fault == "foreign":
        usage["project_id"] = left["project_id"]
    elif fault == "incomplete_refs":
        usage["reservation_ids"].pop()
    elif fault == "shared_refs":
        usage["reservation_ids"][0] = left["budget_usage"]["reservation_ids"][0]
    elif fault == "wrong_contract":
        right["budget_binding"]["contract_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        validate_creation_comparison(left, right)


@pytest.mark.parametrize("field", ["runtime_root", "provider_execution_root", "workspace_id"])
def test_control_cannot_reuse_treatment_runtime_identity(tmp_path, field):
    left, right = comparison_identities(tmp_path)
    right["frozen_configuration"]["runtime_identity"][field] = left["frozen_configuration"]["runtime_identity"][field]
    with pytest.raises(ValueError, match="cannot share runtime"):
        validate_creation_comparison(left, right)


def test_parent_directory_alias_is_not_accepted_as_runtime_isolation(tmp_path):
    left, right = comparison_identities(tmp_path)
    left["frozen_configuration"]["runtime_identity"]["runtime_root"] = str(Path(right["frozen_configuration"]["runtime_identity"]["runtime_root"]) / ".." / "B")
    with pytest.raises(ValueError, match="resolved absolute"):
        validate_creation_comparison(left, right)


@pytest.mark.parametrize("left_field,right_field", [
    ("runtime_root", "runtime_root"),
    ("provider_execution_root", "provider_execution_root"),
    ("runtime_root", "provider_execution_root"),
])
def test_nested_cross_arm_runtime_namespaces_are_not_isolated(tmp_path, left_field, right_field):
    left, right = comparison_identities(tmp_path)
    left_path = left["frozen_configuration"]["runtime_identity"][left_field]
    right["frozen_configuration"]["runtime_identity"][right_field] = str(Path(left_path) / "control")
    with pytest.raises(ValueError, match="runtime directory namespaces"):
        validate_creation_comparison(left, right)


@pytest.mark.parametrize("phase", ["CREATION", "REPAIR"])
def test_later_full_authorization_cannot_retroactively_make_earlier_unequal_opportunity_fair(tmp_path, phase):
    left, right = comparison_identities(tmp_path)
    right["budget_usage"]["creation_opportunity"]["authorized_cumulative_caps"][phase]["calls"] -= 1
    with pytest.raises(ValueError, match="before creation"):
        validate_creation_comparison(left, right)


def test_unknown_first_creation_policy_is_not_inferred_from_current_authorization(tmp_path):
    left, right = comparison_identities(tmp_path)
    right["budget_usage"]["creation_opportunity"] = None
    with pytest.raises(ValueError, match="first creation authorization"):
        validate_creation_comparison(left, right)


def test_priced_execution_does_not_claim_fair_monetary_opportunity_without_phase_usd_caps(tmp_path):
    left, right = comparison_identities(tmp_path)
    for identity in (left, right):
        identity["frozen_configuration"]["comparison_budget"]["accounting_basis"] = "PRICED"
    with pytest.raises(ValueError, match="phase USD"):
        validate_creation_comparison(left, right)


def test_resume_can_change_native_authorization_provenance_without_changing_frozen_opportunity(tmp_path):
    left, _ = comparison_identities(tmp_path)
    previous = deepcopy(left["frozen_configuration"])
    old_binding = deepcopy(left["budget_binding"])
    old_binding["authorization"]["authorized_cumulative_caps"]["CREATION"] = {"calls": 0, "tokens": 0}
    old_binding["authorization"]["authorized_cumulative_caps"]["REPAIR"] = {"calls": 0, "tokens": 0}
    current = deepcopy(previous)
    binding = deepcopy(left["budget_binding"])
    binding["policy_version"] = "fixture-v2"
    binding["authorization"]["authorization_ref"] = "fixture:new-stage-authorization"
    binding["authorization"]["evidence_hash"] = "sha256:" + "8" * 64
    for value in (old_binding, binding):
        value["policy_hash"] = policy_hash({"policy_version": value["policy_version"], "comparison_budget": previous["comparison_budget"], "authorization": value["authorization"]})
    current["cost_accounting"]["authorization_ref"] = binding["authorization"]["authorization_ref"]
    current["runtime_settings"]["NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF"] = binding["authorization"]["authorization_ref"]
    assert creation_resume_semantics(previous, old_binding) == creation_resume_semantics(current, binding)
    current["runtime_settings"]["NOVEL_FORGE_BOOK_CONTEXT_TOKEN_BUDGET"] = "64000"
    assert creation_resume_semantics(previous, old_binding) != creation_resume_semantics(current, binding)


def test_resume_does_not_remove_authorization_binding_validation(tmp_path):
    left, _ = comparison_identities(tmp_path)
    frozen = left["frozen_configuration"]
    frozen["runtime_settings"]["NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF"] = "unverified-ref"
    with pytest.raises(ValueError, match="runtime authorization"):
        creation_resume_semantics(frozen, left["budget_binding"])
