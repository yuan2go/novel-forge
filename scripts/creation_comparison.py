from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from typing import Any

from novel_forge.modules.command_kernel.creative_budget_contract import (
    contract_hash as comparison_contract_hash, validate_comparison_budget,
)
from novel_forge.storage.versioned_policy_repository import policy_hash


_HASH = re.compile(r"sha256:[0-9a-f]{64}")
_POLICY_HASH = re.compile(r"[0-9a-f]{64}")
_UNKNOWN = {"UNKNOWN", "NOT_REPORTED", "UNSPECIFIED", "UNAVAILABLE"}
_USAGE_FIELDS = {
    "calls_used_or_reserved", "conservative_tokens", "recorded_actual_tokens",
    "unmeasured_reserved_tokens",
}
_PROJECT_LIMITS = {
    "NOVEL_FORGE_PROJECT_PROVIDER_CALL_LIMIT": "calls",
    "NOVEL_FORGE_PROVIDER_PROJECT_CALL_LIMIT": "calls",
    "NOVEL_FORGE_PROJECT_PROVIDER_TOKEN_LIMIT": "tokens",
    "NOVEL_FORGE_PROVIDER_PROJECT_TOKEN_LIMIT": "tokens",
}
_AUTHORIZATION_SETTING = "NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF"
_EQUAL_RUNTIME_SETTINGS = {
    "NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL",
    "NOVEL_FORGE_OPERATION_PROVIDER_CAP",
    "NOVEL_FORGE_PROJECT_DAILY_PROVIDER_CAP",
    "NOVEL_FORGE_DAILY_PROVIDER_CAP",
    "NOVEL_FORGE_CHAPTER_PROVIDER_CAP",
    "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID",
    "NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID",
    "NOVEL_FORGE_BOOK_CONTEXT_TOKEN_BUDGET",
    "NOVEL_FORGE_BOOK_QUALITY_CONTEXT_TOKEN_BUDGET",
    "NOVEL_FORGE_BOOK_OPENING_PROVIDER_CALL_LIMIT",
    "NOVEL_FORGE_BOOK_OPENING_PROVIDER_COST_LIMIT",
    "NOVEL_FORGE_BOOK_OPENING_PROVIDER_TOKEN_LIMIT",
    "NOVEL_FORGE_BOOK_OPENING_PROVIDER_PER_CALL_TOKEN_LIMIT",
    "NOVEL_FORGE_BOOK_OPENING_PROVIDER_PER_CALL_COST_LIMIT",
    "NOVEL_FORGE_BOOK_OPENING_PROVIDER_WINDOW_SECONDS",
    "NOVEL_FORGE_CODEX_ACCOUNTING_MODE",
    "NOVEL_FORGE_CODEX_ACCOUNT_IDENTITY_REF",
    "NOVEL_FORGE_CODEX_CLI_VERSION",
    "NOVEL_FORGE_CODEX_EXECUTABLE_SHA256",
    "NOVEL_FORGE_CODEX_CONFIGURATION_REF",
    "NOVEL_FORGE_OPERATION_PROVIDER_CALL_LIMIT",
    "NOVEL_FORGE_PROJECT_DAILY_PROVIDER_CALL_LIMIT",
    "NOVEL_FORGE_PROVIDER_DAILY_CALL_LIMIT",
    "NOVEL_FORGE_GLOBAL_DAILY_PROVIDER_CALL_LIMIT",
    "NOVEL_FORGE_OPERATION_PROVIDER_TOKEN_LIMIT",
    "NOVEL_FORGE_PROJECT_DAILY_PROVIDER_TOKEN_LIMIT",
    "NOVEL_FORGE_PROVIDER_DAILY_TOKEN_LIMIT",
    "NOVEL_FORGE_GLOBAL_DAILY_PROVIDER_TOKEN_LIMIT",
}
COMPARISON_RUNTIME_SETTINGS = frozenset(
    _EQUAL_RUNTIME_SETTINGS | _PROJECT_LIMITS.keys() | {_AUTHORIZATION_SETTING}
)
_ROUTE_FIELDS = {
    "model_profile", "route_policy", "fallback_policy", "backend_version",
    "auth_profile_ref", "prompt_version", "skill_version", "system_instruction_hash",
    "template_hash", "skill_content_hash", "prompt_compiler_version", "output_schema_ref",
    "model_context_limit", "token_accounting_method", "token_accounting_evidence_ref",
    "token_safety_margin", "token_framing_overhead",
}
_FROZEN_FIELDS = {
    "contract_version", "run_key", "brief_input_hash", "creation_policy",
    "formation_policy", "implementation_identity", "models", "cost_accounting",
    "runtime_settings", "comparison_budget", "runtime_identity", "input_snapshot",
}


def _object(value: Any, label: str, *, fields: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Comparison requires {label}")
    if fields is not None and set(value) != fields:
        raise ValueError(f"Comparison {label} has missing or unknown fields: {sorted(set(value) ^ fields)}")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value.strip().upper() in _UNKNOWN:
        raise ValueError(f"Comparison requires known {label}")
    return value


def _hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError(f"Comparison requires exact {label}")
    return value


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"Comparison requires finite integer {label} >= {minimum}")
    return value


def _allocation(value: Any, label: str, *, positive: bool = False, paired: bool = True) -> dict[str, int]:
    value = _object(value, label, fields={"calls", "tokens"})
    for key in value:
        _integer(value[key], f"{label}.{key}", minimum=int(positive))
    if paired and bool(value["calls"]) != bool(value["tokens"]):
        raise ValueError(f"Comparison {label} must allocate calls and tokens together")
    return value


def _authorized_caps(value: Any, arm: dict[str, Any], *, require_creation: bool) -> dict[str, Any]:
    caps = _object(value, "authorized cumulative caps", fields={"SOURCE", "CREATION", "REPAIR"})
    for phase, cap in caps.items():
        _allocation(cap, "authorized " + phase, paired=False)
        planned = arm[phase.lower() + "_allocation"]
        if any(cap[key] > planned[key] for key in cap):
            raise ValueError("Comparison authorization exceeds the immutable phase opportunity")
        if require_creation and phase in {"CREATION", "REPAIR"} and cap != planned:
            raise ValueError("Comparison creative opportunity was not fully authorized before creation")
    return caps


def _budget_binding(value: Any, arm: dict[str, Any], contract: dict[str, Any], *, require_creation: bool = True) -> dict[str, Any]:
    binding = _object(value, "native budget binding", fields={
        "owner", "policy_version", "policy_hash", "contract_hash", "subject_id", "authorization",
    })
    if binding["owner"] != "CREATIVE_EXPERIMENT_BUDGET":
        raise ValueError("Comparison budget policy owner is invalid")
    _text(binding["policy_version"], "budget policy version")
    if binding["subject_id"] != "project:" + arm["project_id"]:
        raise ValueError("Comparison budget policy subject belongs to another project")
    _hash(binding["contract_hash"], "budget binding contract_hash")
    if binding["contract_hash"] != comparison_contract_hash(contract):
        raise ValueError("Comparison native budget binding differs from the frozen contract")
    authorization = _object(binding["authorization"], "native budget authorization", fields={
        "authorization_ref", "evidence_hash", "project_id", "book_id", "authorized_cumulative_caps",
    })
    _text(authorization["authorization_ref"], "native authorization reference")
    _hash(authorization["evidence_hash"], "native authorization evidence")
    if any(authorization[key] != arm[key] for key in ("project_id", "book_id")):
        raise ValueError("Comparison authorization belongs to another arm")
    _authorized_caps(authorization["authorized_cumulative_caps"], arm, require_creation=require_creation)
    if binding["policy_hash"] != policy_hash({
        "policy_version": binding["policy_version"], "comparison_budget": contract,
        "authorization": authorization,
    }):
        raise ValueError("Comparison native policy hash differs from its exact authorization content")
    return binding


def _usage(identity: dict[str, Any], arm: dict[str, Any], contract_hash: str, shared_cap: dict[str, int]) -> dict[str, Any]:
    usage = _object(identity.get("budget_usage"), "actual PostgreSQL budget usage", fields={
        "contract_hash", "project_id", "book_id", "phases", "project_total", "shared_total", "reservation_ids", "evidence_class", "creation_opportunity",
    })
    if usage["evidence_class"] != "POSTGRESQL_BUDGET_LEDGER" or usage["contract_hash"] != contract_hash:
        raise ValueError("Comparison requires exact native ledger export provenance")
    if any(usage[key] != arm[key] for key in ("project_id", "book_id")):
        raise ValueError("Comparison budget usage belongs to another arm")
    phases = _object(usage["phases"], "ledger phases", fields={"SOURCE", "CREATION", "REPAIR"})
    for phase, value in {**phases, "PROJECT_TOTAL": usage["project_total"]}.items():
        fields = _object(value, phase + " usage", fields=_USAGE_FIELDS)
        for key, count in fields.items():
            _integer(count, phase + "." + key)
        if fields["conservative_tokens"] != fields["recorded_actual_tokens"] + fields["unmeasured_reserved_tokens"]:
            raise ValueError("Comparison ledger token accounting does not reconcile")
        if fields["unmeasured_reserved_tokens"]:
            raise ValueError("Comparison cannot establish complete usage while reserved tokens remain unmeasured")
        cap = arm["project_total" if phase == "PROJECT_TOTAL" else phase.lower() + "_allocation"]
        if fields["calls_used_or_reserved"] > cap["calls"] or fields["conservative_tokens"] > cap["tokens"]:
            raise ValueError("Comparison actual ledger usage exceeds its frozen phase budget")
    if any(usage["project_total"][key] != sum(phase[key] for phase in phases.values()) for key in _USAGE_FIELDS):
        raise ValueError("Comparison project ledger total differs from the phase totals")
    shared = _object(usage["shared_total"], "shared ledger total", fields=_USAGE_FIELDS)
    for key, value in shared.items():
        _integer(value, "shared ledger " + key)
        if value < usage["project_total"][key]:
            raise ValueError("Comparison shared ledger total omits this project")
    if shared["calls_used_or_reserved"] > shared_cap["calls"] or shared["conservative_tokens"] > shared_cap["tokens"]:
        raise ValueError("Comparison shared ledger usage exceeds the frozen experiment ceiling")
    refs = usage["reservation_ids"]
    if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref for ref in refs) or len(refs) != len(set(refs)):
        raise ValueError("Comparison requires unique native budget reservation references")
    if len(refs) < usage["project_total"]["calls_used_or_reserved"]:
        raise ValueError("Comparison ledger usage lacks its reservation references")
    opportunity = _object(usage["creation_opportunity"], "first creation authorization", fields={
        "first_reservation_id", "policy_hash", "authorized_cumulative_caps",
    })
    if opportunity["first_reservation_id"] not in refs or not phases["CREATION"]["calls_used_or_reserved"]:
        raise ValueError("Comparison lacks the first creative reservation authorization")
    if not isinstance(opportunity["policy_hash"], str) or not _POLICY_HASH.fullmatch(opportunity["policy_hash"]):
        raise ValueError("Comparison requires the exact first creation policy hash")
    _authorized_caps(opportunity["authorized_cumulative_caps"], arm, require_creation=True)
    return deepcopy(usage)


def _models(value: Any) -> dict[str, Any]:
    models = _object(value, "frozen model, Prompt and Skill routes")
    if not models:
        raise ValueError("Comparison requires frozen model, Prompt and Skill routes")
    for name, route in models.items():
        _object(route, f"route {name}", fields=_ROUTE_FIELDS)
        profile = _object(route["model_profile"], "model profile")
        for key in ("model_provider", "model_id", "reasoning_effort", "backend_id"):
            _text(profile.get(key), "model profile " + key)
        for key in ("route_policy", "fallback_policy"):
            if not _object(route[key], key):
                raise ValueError("Comparison requires the effective " + key)
        for key in ("system_instruction_hash", "template_hash", "skill_content_hash"):
            _hash(route[key], key)
        for key in _ROUTE_FIELDS - {"model_profile", "route_policy", "fallback_policy", "model_context_limit", "token_safety_margin", "token_framing_overhead"}:
            _text(route[key], key)
        _integer(route["model_context_limit"], "model context limit", minimum=1)
        for key in ("token_safety_margin", "token_framing_overhead"):
            _integer(route[key], key)
    return models


def _runtime(identity: dict[str, Any], frozen: dict[str, Any], arm: dict[str, Any], contract: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    runtime = _object(frozen.get("runtime_settings"), "runtime_settings")
    unknown = set(runtime) - COMPARISON_RUNTIME_SETTINGS
    if unknown:
        raise ValueError("Comparison has unclassified runtime settings: " + ", ".join(sorted(unknown)))
    for key, value in runtime.items():
        _text(value, key)
    for key in ("NOVEL_FORGE_PROJECT_PROVIDER_CALL_LIMIT", "NOVEL_FORGE_PROJECT_PROVIDER_TOKEN_LIMIT"):
        _text(runtime.get(key), key)
    for key, dimension in _PROJECT_LIMITS.items():
        if key in runtime and runtime[key] != str(arm["project_total"][dimension]):
            raise ValueError("Comparison project budget setting differs from its arm allocation: " + key)
    accounting = _object(frozen.get("cost_accounting"), "cost_accounting", fields={
        "accounting_basis", "authorization_ref", "authorized_total_usd", "monetary_cost_status",
    })
    authorization_ref = binding["authorization"]["authorization_ref"]
    if accounting["accounting_basis"] != contract["accounting_basis"] or accounting["authorization_ref"] != authorization_ref:
        raise ValueError("Comparison accounting must retain its exact budget authorization binding")
    if contract["accounting_basis"] == "ACCOUNT_ENTITLEMENT":
        if accounting["authorized_total_usd"] is not None or accounting["monetary_cost_status"] != "UNKNOWN":
            raise ValueError("Comparison account entitlement cannot invent monetary amounts")
        for key in ("NOVEL_FORGE_CODEX_ACCOUNT_IDENTITY_REF", "NOVEL_FORGE_CODEX_CLI_VERSION", "NOVEL_FORGE_CODEX_EXECUTABLE_SHA256", "NOVEL_FORGE_CODEX_CONFIGURATION_REF"):
            _text(runtime.get(key), key)
        if runtime.get(_AUTHORIZATION_SETTING) != authorization_ref:
            raise ValueError("Comparison runtime authorization is not bound to its budget")
        if runtime.get("NOVEL_FORGE_CODEX_ACCOUNTING_MODE") != "ACCOUNT_ENTITLEMENT":
            raise ValueError("Comparison runtime accounting mode differs")
    else:
        try:
            amount = Decimal(accounting["authorized_total_usd"])
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("Comparison priced authorization amount is unknown") from exc
        if not amount.is_finite() or amount <= 0 or accounting["monetary_cost_status"] != "ESTIMATED":
            raise ValueError("Comparison priced authorization amount is invalid")
    scope = _object(frozen.get("runtime_identity"), "runtime_identity", fields={
        "project_id", "book_id", "workspace_id", "run_key", "runtime_root", "provider_execution_root",
    })
    for key, value in scope.items():
        _text(value, "runtime identity " + key)
    for key in ("project_id", "book_id"):
        if scope[key] != arm[key] or identity.get(key) != arm[key]:
            raise ValueError("Comparison runtime belongs to another arm")
    if scope["run_key"] != frozen.get("run_key") or scope["run_key"] != identity.get("run_key"):
        raise ValueError("Comparison runtime run identity is not frozen consistently")
    for key in ("runtime_root", "provider_execution_root"):
        if not Path(scope[key]).is_absolute() or str(Path(scope[key]).resolve()) != scope[key]:
            raise ValueError("Comparison requires a resolved absolute " + key)
    snapshot = _object(frozen.get("input_snapshot"), "input snapshot", fields={"manifest_file_hash", "integrity", "files"})
    _hash(snapshot["manifest_file_hash"], "input freeze manifest")
    if snapshot["integrity"] != "PINNED_MANIFEST_AND_FILES":
        raise ValueError("Comparison requires independently pinned frozen input bytes")
    files = _object(snapshot["files"], "consumed input file hashes")
    if not {"brief", "creation", "formation", "budget"}.issubset(files) or set(files) - {"brief", "creation", "formation", "budget", "knowledge"}:
        raise ValueError("Comparison consumed input roles are missing or unknown")
    for role, entry in files.items():
        _object(entry, role + " input hash", fields={"name", "content_hash"})
        _hash(entry["content_hash"], role + " input hash")
        name = _text(entry["name"], role + " input name")
        if Path(name).name != name:
            raise ValueError("Comparison input file name must belong to its freeze")
    return scope


def validate_creation_comparison(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    identities = (left, right)
    frozen = [_object(item.get("frozen_configuration"), "frozen_configuration", fields=_FROZEN_FIELDS) for item in identities]
    contracts = [validate_comparison_budget(item["comparison_budget"], require_both_arms=True) for item in frozen]
    if contracts[0] != contracts[1]:
        raise ValueError("Comparison arms must freeze the same complete budget contract")
    contract = contracts[0]
    if contract["accounting_basis"] == "PRICED":
        raise ValueError("Comparison cannot establish monetary opportunity without phase USD allocations")
    digest = comparison_contract_hash(contract)
    arms = {item["arm"]: item for item in contract["arms"]}
    usages, scopes = [], []
    for index, name in enumerate(("A", "B")):
        identity, configuration = identities[index], frozen[index]
        if configuration["contract_version"] != "creation-pilot.v1":
            raise ValueError("Comparison frozen configuration version is unsupported")
        for key in ("implementation_identity", "brief_input_hash", "formation_policy"):
            if not identity.get(key) or identity[key] != identities[1-index].get(key) or identity[key] != configuration[key]:
                raise ValueError("Comparison frozen inputs differ: " + key)
        _models(configuration["models"])
        binding = _budget_binding(identity.get("budget_binding"), arms[name], contract)
        scopes.append(_runtime(identity, configuration, arms[name], contract, binding))
        usages.append(_usage(identity, arms[name], digest, contract["shared_total"]))
    if frozen[0]["models"] != frozen[1]["models"]:
        raise ValueError("Comparison requires identical frozen model, Prompt and Skill routes")
    policies = []
    for item in frozen:
        policy = deepcopy(_object(item["creation_policy"], "creation policy"))
        try:
            policy["profiles"]["production_profile"]["content"].pop("knowledge_access_policy", None)
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("Comparison requires frozen creation and revision policies") from exc
        policies.append(policy)
    if policies[0] != policies[1]:
        raise ValueError("Comparison word targets, revision policy, context policy or future intervention differ")
    runtimes = [item["runtime_settings"] for item in frozen]
    for key in _EQUAL_RUNTIME_SETTINGS:
        if runtimes[0].get(key) != runtimes[1].get(key):
            raise ValueError("Comparison frozen creative budgets or runtime policy differs: " + key)
    accounting_values = [{key: value for key, value in item["cost_accounting"].items() if key != "authorization_ref"} for item in frozen]
    if accounting_values[0] != accounting_values[1]:
        raise ValueError("Comparison monetary opportunity differs without a matching phase allocation")
    for key in ("project_id", "book_id", "workspace_id", "run_key", "runtime_root", "provider_execution_root"):
        if scopes[0][key] == scopes[1][key]:
            raise ValueError("Comparison arms cannot share runtime " + key)
    for left_key in ("runtime_root", "provider_execution_root"):
        for right_key in ("runtime_root", "provider_execution_root"):
            left_path, right_path = Path(scopes[0][left_key]), Path(scopes[1][right_key])
            if left_path.is_relative_to(right_path) or right_path.is_relative_to(left_path):
                raise ValueError("Comparison arms cannot share runtime directory namespaces")
    if set(usages[0]["reservation_ids"]) & set(usages[1]["reservation_ids"]):
        raise ValueError("Comparison arms cannot share Provider budget reservations")
    return {
        "contract_version": "creative-opportunity-comparison.v1",
        "status": "COMPARABLE_RECORDED_OPPORTUNITY",
        "authority": "READ_ONLY_EXPORT_VALIDATION",
        "budget_contract_hash": digest,
        "equal_required": ["implementation_identity", "brief_input_hash", "formation_policy", "models", "creation_policy_except_book_knowledge", "creation_allocation", "repair_allocation", "runtime_creative_policy", "account_and_authorization_binding"],
        "classified_differences": [
            {"category": "PROJECT_AND_SOURCE_ALLOCATION", "A": arms["A"], "B": arms["B"], "constraint": "Equal creative/repair allocation; project sum within the shared ceiling"},
            {"category": "ISOLATED_RUNTIME_IDENTITY", "A": scopes[0], "B": scopes[1], "constraint": "Independent scopes; accepted Context and upper-plan lineage require separate checks"},
            {"category": "ACTUAL_LEDGER_USAGE", "A": usages[0], "B": usages[1], "constraint": "Actual consumption may differ within identical creative opportunities"},
            {"category": "AUTHORIZATION_PROVENANCE", "A": left["budget_binding"], "B": right["budget_binding"], "constraint": "Each native policy binds its exact arm and fixed plan; full creative opportunity preceded creation"},
        ],
        "authorization": "REFERENCE_VALIDATED_NOT_GRANTED",
        "real_provider_execution": "NOT_ESTABLISHED_BY_COMPARISON",
        "independent_editorial": "NOT_PROVEN",
        "creative_benefit": "NOT_PROVEN",
    }


def creation_resume_semantics(frozen: dict[str, Any], budget_binding: dict[str, Any], *, require_creation: bool = False) -> dict[str, Any]:
    configuration = _object(frozen, "frozen_configuration", fields=_FROZEN_FIELDS)
    contract = validate_comparison_budget(configuration["comparison_budget"])
    digest = comparison_contract_hash(contract)
    scope = _object(configuration["runtime_identity"], "runtime identity")
    arms = [arm for arm in contract["arms"] if all(arm[key] == scope.get(key) for key in ("project_id", "book_id"))]
    if len(arms) != 1:
        raise ValueError("Creation resume must retain one exact budget arm")
    binding = _budget_binding(budget_binding, arms[0], contract, require_creation=require_creation)
    _models(configuration["models"])
    _runtime(scope, configuration, arms[0], contract, binding)
    normalized = deepcopy(configuration)
    provenance = {"native_budget_contract_hash": digest}
    normalized["cost_accounting"]["authorization_ref"] = provenance
    if _AUTHORIZATION_SETTING in normalized["runtime_settings"]:
        normalized["runtime_settings"][_AUTHORIZATION_SETTING] = deepcopy(provenance)
    return normalized
