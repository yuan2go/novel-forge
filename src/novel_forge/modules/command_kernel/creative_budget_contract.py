from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import re
from typing import Any

from .errors import KernelError


PHASES = ("SOURCE", "CREATION", "REPAIR")
SINGLE_BOOK_VERSION = "creative-single-book-budget.v2"
PRODUCTION_BOOK_VERSION = "creative-book-production-budget.v3"
PAIRED_SAMPLES_VERSION = "creative-paired-samples-budget.v5"
PAIRED_SAMPLES_PHASES = (*PHASES, "QUALIFICATION")
PROVIDER_CAMPAIGN_VERSION = "creative-provider-campaign-budget.v4"
PROVIDER_RENEWAL_VERSION = "creative-provider-campaign-budget.v5"
PROVIDER_BUDGET_VERSIONS = {PROVIDER_CAMPAIGN_VERSION, PROVIDER_RENEWAL_VERSION}
PROVIDER_CAMPAIGN_PHASES = ("REFERENCE", "SCREENING", "CALIBRATION", "HOLDOUT", "SOURCE", "DESIGN", "PRODUCTION", "REPAIR")
SINGLE_BOOK_VERSIONS = {SINGLE_BOOK_VERSION, PRODUCTION_BOOK_VERSION}
SINGLE_BOOK_PHASES = ("SOURCE", "DESIGN", "CREATION_EARLY", "CREATION_LATE", "REPAIR")
_ALLOCATIONS = dict(zip(PHASES, ("source_allocation", "creation_allocation", "repair_allocation"), strict=True))
_HASH = re.compile(r"sha256:[0-9a-f]{64}")
_UNKNOWN = {"UNKNOWN", "NOT_REPORTED", "UNSPECIFIED", "UNAVAILABLE"}


def _object_schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


_TEXT_SCHEMA = {"type": "string", "minLength": 1, "pattern": r"\S"}
_ALLOCATION_SCHEMA = _object_schema({key: {"type": "integer", "minimum": 0} for key in ("calls", "tokens")})
_ARM_SCHEMA = _object_schema({
    "arm": {"type": "string", "enum": ["A", "B"]},
    "project_id": _TEXT_SCHEMA,
    "book_id": _TEXT_SCHEMA,
    **{key: _ALLOCATION_SCHEMA for key in ("project_total", *_ALLOCATIONS.values())},
})
POLICY_SCHEMA = _object_schema({
    "policy_version": _TEXT_SCHEMA,
    "comparison_budget": _object_schema({
        "contract_version": {"type": "string", "const": "creative-experiment-budget.v1"},
        "experiment_id": _TEXT_SCHEMA,
        "accounting_basis": {"type": "string", "const": "ACCOUNT_ENTITLEMENT"},
        "shared_total": _ALLOCATION_SCHEMA,
        "arms": {"type": "array", "minItems": 1, "maxItems": 2, "items": _ARM_SCHEMA},
    }),
    "authorization": _object_schema({
        "authorization_ref": _TEXT_SCHEMA,
        "evidence_hash": {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"},
        "project_id": _TEXT_SCHEMA,
        "book_id": _TEXT_SCHEMA,
        "authorized_cumulative_caps": _object_schema({phase: _ALLOCATION_SCHEMA for phase in PHASES}),
    }),
})
V1_POLICY_SCHEMA = POLICY_SCHEMA
V2_POLICY_SCHEMA = deepcopy(V1_POLICY_SCHEMA)
_V2_PLAN_SCHEMA = V2_POLICY_SCHEMA["properties"]["comparison_budget"]
_V2_PLAN_SCHEMA["properties"]["contract_version"] = {"type": "string", "const": SINGLE_BOOK_VERSION}
_V2_ARM_SCHEMA = _object_schema({
    "arm": {"type": "string", "const": "SINGLE"},
    "project_id": _TEXT_SCHEMA,
    "book_id": _TEXT_SCHEMA,
    **{key: _ALLOCATION_SCHEMA for key in ("project_total", *(phase.lower() + "_allocation" for phase in SINGLE_BOOK_PHASES))},
    "chapter_ranges": _object_schema({
        "CREATION_EARLY": {"type": "array", "const": [1, 6]},
        "CREATION_LATE": {"type": "array", "const": [7, 12]},
    }),
})
_V2_PLAN_SCHEMA["properties"]["arms"] = {"type": "array", "minItems": 1, "maxItems": 1, "items": _V2_ARM_SCHEMA}
_V2_AUTH_SCHEMA = V2_POLICY_SCHEMA["properties"]["authorization"]
_V2_AUTH_SCHEMA["properties"]["authorized_cumulative_caps"] = _object_schema({phase: _ALLOCATION_SCHEMA for phase in SINGLE_BOOK_PHASES})
_V2_AUTH_SCHEMA["properties"]["business_scope"] = _object_schema({
    "source_allowed": {"type": "boolean"},
    "design_allowed": {"type": "boolean"},
    "max_chapter_number": {"type": "integer", "minimum": 0, "maximum": 12},
})
_V2_AUTH_SCHEMA["required"].append("business_scope")
V3_POLICY_SCHEMA = deepcopy(V2_POLICY_SCHEMA)
_V3_PLAN_SCHEMA = V3_POLICY_SCHEMA["properties"]["comparison_budget"]
_V3_PLAN_SCHEMA["properties"]["contract_version"] = {"type": "string", "const": PRODUCTION_BOOK_VERSION}
_V3_PLAN_SCHEMA["properties"]["previous_policy"] = _object_schema({
    "policy_version": _TEXT_SCHEMA,
    "policy_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "contract_hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
})
_V3_PLAN_SCHEMA["required"].append("previous_policy")
_V3_ARM_SCHEMA = _V3_PLAN_SCHEMA["properties"]["arms"]["items"]
_V3_ARM_SCHEMA["properties"]["chapter_ranges"] = _object_schema({
    phase: {"type": "array", "minItems": 2, "maxItems": 2,
            "items": {"type": "integer", "minimum": 1}}
    for phase in ("CREATION_EARLY", "CREATION_LATE")
})
V3_POLICY_SCHEMA["properties"]["authorization"]["properties"]["business_scope"]["properties"]["max_chapter_number"].pop("maximum")
POLICY_SCHEMA = V1_POLICY_SCHEMA
V5_POLICY_SCHEMA = deepcopy(V1_POLICY_SCHEMA)
_V5_PLAN_SCHEMA = V5_POLICY_SCHEMA["properties"]["comparison_budget"]
_V5_PLAN_SCHEMA["properties"]["contract_version"] = {"type": "string", "const": PAIRED_SAMPLES_VERSION}
_V5_ARM_SCHEMA = deepcopy(_ARM_SCHEMA)
_V5_ARM_SCHEMA["properties"].update(sample_id=_TEXT_SCHEMA, stage={"type": "string", "enum": ["PILOT", "EXPLORATION"]})
_V5_ARM_SCHEMA["properties"]["qualification_allocation"] = _ALLOCATION_SCHEMA
_V5_ARM_SCHEMA["required"].extend(["sample_id", "stage", "qualification_allocation"])
_V5_PLAN_SCHEMA["properties"]["arms"] = {"type": "array", "minItems": 4, "maxItems": 16, "items": _V5_ARM_SCHEMA}
V5_POLICY_SCHEMA["properties"]["authorization"]["properties"]["authorized_cumulative_caps"] = _object_schema({phase: _ALLOCATION_SCHEMA for phase in PAIRED_SAMPLES_PHASES})
_MIXED_ALLOCATION_SCHEMA = _object_schema({
    **_ALLOCATION_SCHEMA["properties"],
    "priced_usd": {"type": "string", "pattern": r"^(0|[1-9][0-9]*)(\.[0-9]+)?$"},
})
V4_POLICY_SCHEMA = _object_schema({
    "policy_version": _TEXT_SCHEMA,
    "comparison_budget": _object_schema({
        "contract_version": {"const": PROVIDER_CAMPAIGN_VERSION},
        "experiment_id": _TEXT_SCHEMA,
        "manifest_hash": {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"},
        "expires_at": {"type": "string", "format": "date-time"},
        "accounting_basis": {"const": "MIXED"},
        "shared_total": _MIXED_ALLOCATION_SCHEMA,
        "arms": {"type": "array", "minItems": 1, "maxItems": 1, "items": _object_schema({
            "arm": {"const": "SINGLE"}, "project_id": _TEXT_SCHEMA, "book_id": _TEXT_SCHEMA,
            "project_total": _MIXED_ALLOCATION_SCHEMA,
            **{phase.lower() + "_allocation": _MIXED_ALLOCATION_SCHEMA for phase in PROVIDER_CAMPAIGN_PHASES},
            "chapter_ranges": _object_schema({"PRODUCTION": {
                "type": "array", "minItems": 2, "maxItems": 2,
                "items": {"type": "integer", "minimum": 1},
            }}),
        })},
        "entitlements": {"type": "array", "items": _object_schema({
            "provider": _TEXT_SCHEMA, "authorization_ref": _TEXT_SCHEMA,
            **{key: {"type": "integer", "minimum": 1} for key in ("calls", "tokens")},
        })},
    }),
    "authorization": _object_schema({
        "authorization_ref": _TEXT_SCHEMA, "project_id": _TEXT_SCHEMA, "book_id": _TEXT_SCHEMA,
        "evidence_hash": {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"},
        "authorized_cumulative_caps": _object_schema({phase: _MIXED_ALLOCATION_SCHEMA for phase in PROVIDER_CAMPAIGN_PHASES}),
        "business_scope": _object_schema({
            "source_allowed": {"type": "boolean"}, "design_allowed": {"type": "boolean"},
            "max_chapter_number": {"type": "integer", "minimum": 0},
        }),
    }),
})
V4_MONETARY_AMENDMENT_SCHEMA = deepcopy(V4_POLICY_SCHEMA)
_V4_AMENDED_PLAN = V4_MONETARY_AMENDMENT_SCHEMA["properties"]["comparison_budget"]
_V4_AMENDED_PLAN["properties"]["previous_policy"] = deepcopy(_V3_PLAN_SCHEMA["properties"]["previous_policy"])
_V4_AMENDED_PLAN["required"].append("previous_policy")

PROVIDER_RENEWAL_POLICY_SCHEMA = deepcopy(V4_MONETARY_AMENDMENT_SCHEMA)
_RENEWAL_PLAN_SCHEMA = PROVIDER_RENEWAL_POLICY_SCHEMA["properties"]["comparison_budget"]
_RENEWAL_PLAN_SCHEMA["properties"]["contract_version"] = {"const": PROVIDER_RENEWAL_VERSION}
_RENEWAL_PLAN_SCHEMA["properties"]["renewal"] = _object_schema({
    "authorized_at": {"type": "string", "format": "date-time"},
    "additional_total": _MIXED_ALLOCATION_SCHEMA,
    "carry_forward": _object_schema({
        "reservation_ids": {"type": "array", "items": _TEXT_SCHEMA},
        "shared_total": _MIXED_ALLOCATION_SCHEMA,
        "phases": _object_schema({phase: _MIXED_ALLOCATION_SCHEMA for phase in PROVIDER_CAMPAIGN_PHASES}),
        "entitlements": deepcopy(_RENEWAL_PLAN_SCHEMA["properties"]["entitlements"]),
    }),
})
_RENEWAL_PLAN_SCHEMA["required"].append("renewal")
_RENEWAL_PLAN_SCHEMA["properties"]["entitlements"]["items"]["properties"]["tokens"]["minimum"] = 0
_RENEWAL_PLAN_SCHEMA["properties"]["renewal"]["properties"]["carry_forward"]["properties"]["entitlements"]["items"]["properties"]["tokens"]["minimum"] = 0


def _invalid(message: str) -> KernelError:
    return KernelError("CREATIVE_BUDGET_CONTRACT_INVALID", message)


def _object(value: Any, label: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _invalid(f"Comparison requires {label} object")
    if set(value) != fields:
        raise _invalid(f"Comparison {label} has missing or unknown fields")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value.strip().upper() in _UNKNOWN:
        raise _invalid(f"Comparison requires known {label}")
    return value


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise _invalid(f"Comparison requires finite integer {label} >= {minimum}")
    return value


def _allocation(value: Any, label: str, *, positive: bool = False, paired: bool = True) -> dict[str, int]:
    result = _object(value, label, {"calls", "tokens"})
    for key, amount in result.items():
        _integer(amount, f"{label}.{key}", int(positive))
    if paired and bool(result["calls"]) != bool(result["tokens"]):
        raise _invalid(f"Comparison {label} must allocate calls and tokens together")
    return result


def validate_comparison_budget(value: Any, *, require_both_arms: bool = False) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("contract_version") in PROVIDER_BUDGET_VERSIONS:
        return _validate_provider_campaign(value, require_both_arms=require_both_arms)
    production = isinstance(value, dict) and value.get("contract_version") == PRODUCTION_BOOK_VERSION
    contract = _object(value, "comparison_budget", {
        "contract_version", "experiment_id", "accounting_basis", "shared_total", "arms",
        *({"previous_policy"} if production else set()),
    })
    if not isinstance(contract["contract_version"], str):
        raise _invalid("Comparison budget contract version must be a string")
    if contract["contract_version"] in SINGLE_BOOK_VERSIONS:
        return _validate_single_book_budget(contract, require_both_arms=require_both_arms)
    if contract["contract_version"] == PAIRED_SAMPLES_VERSION:
        return _validate_paired_samples_budget(contract)
    if contract["contract_version"] != "creative-experiment-budget.v1":
        raise _invalid("Comparison budget contract version is unsupported")
    _text(contract["experiment_id"], "experiment_id")
    if not isinstance(contract["accounting_basis"], str) or contract["accounting_basis"] not in {"ACCOUNT_ENTITLEMENT", "PRICED"}:
        raise _invalid("Comparison budget accounting basis is unsupported")
    shared = _allocation(contract["shared_total"], "shared_total", positive=True)
    arms = contract["arms"]
    if not isinstance(arms, list) or not 1 <= len(arms) <= 2:
        raise _invalid("Comparison budget requires the explicit A/B allocation")
    by_arm = {}
    for item in arms:
        arm = _object(item, "arm allocation", {
            "arm", "project_id", "book_id", "project_total", *_ALLOCATIONS.values(),
        })
        name = _text(arm["arm"], "arm")
        if name not in {"A", "B"} or name in by_arm:
            raise _invalid("Comparison budget arm identities must be unique A/B")
        by_arm[name] = arm
        for key in ("project_id", "book_id"):
            _text(arm[key], key)
        for key in ("project_total", *_ALLOCATIONS.values()):
            _allocation(arm[key], key, positive=key in {"project_total", "creation_allocation"})
        if name == "B" and arm["source_allocation"] != {"calls": 0, "tokens": 0}:
            raise _invalid("Comparison control cannot allocate external Source work")
        for key in shared:
            if arm["project_total"][key] != sum(arm[field][key] for field in _ALLOCATIONS.values()):
                raise _invalid("Comparison project total must equal its frozen phase allocations")
    if (require_both_arms and set(by_arm) != {"A", "B"}) or (len(arms) == 1 and set(by_arm) != {"A"}):
        raise _invalid("Comparison requires both A/B arms; only Source preparation may freeze A alone")
    for key in shared:
        if sum(arm["project_total"][key] for arm in arms) > shared[key]:
            raise _invalid("Comparison project allocations exceed the shared authorized ceiling")
    if len(arms) == 2:
        for key in ("project_id", "book_id"):
            if by_arm["A"][key] == by_arm["B"][key]:
                raise _invalid(f"Comparison arms must have independent {key}")
        for key in ("creation_allocation", "repair_allocation"):
            if by_arm["A"][key] != by_arm["B"][key]:
                raise _invalid(f"Comparison creative opportunity differs: {key}")
    return deepcopy(contract)


def _validate_paired_samples_budget(contract: dict[str, Any]) -> dict[str, Any]:
    _text(contract["experiment_id"], "experiment_id")
    if contract["accounting_basis"] != "ACCOUNT_ENTITLEMENT":
        raise _invalid("Paired samples require a single ACCOUNT_ENTITLEMENT lane; mixed billing is not authorized")
    total = _allocation(contract["shared_total"], "shared_total", positive=True)
    arms = contract["arms"]
    if not isinstance(arms, list) or len(arms) not in {4, 16}:
        raise _invalid("Paired samples require two pilot pairs or two pilot and six exploration pairs")
    samples: dict[str, list[dict[str, Any]]] = {}
    projects, books = set(), set()
    for item in arms:
        arm = _object(item, "sample arm", {"sample_id", "stage", "arm", "project_id", "book_id", "project_total", "qualification_allocation", *_ALLOCATIONS.values()})
        sample = _text(arm["sample_id"], "sample_id")
        if not isinstance(arm["stage"], str) or arm["stage"] not in {"PILOT", "EXPLORATION"}:
            raise _invalid("Paired sample stage is invalid")
        _allocation(arm["qualification_allocation"], "qualification_allocation")
        _allocation(arm["project_total"], "project_total", positive=True)
        for key, seen in (("project_id", projects), ("book_id", books)):
            value = _text(arm[key], key)
            if value in seen:
                raise _invalid("Paired samples require independent project and Book identities")
            seen.add(value)
        samples.setdefault(sample, []).append(arm)
    stages = {"PILOT": 0, "EXPLORATION": 0}
    for pair in samples.values():
        if len(pair) != 2 or {arm["arm"] for arm in pair} != {"A", "B"} or len({arm["stage"] for arm in pair}) != 1:
            raise _invalid("Every sample requires one A/B pair in the same stage")
        stages[pair[0]["stage"]] += 1
        if pair[0]["qualification_allocation"] != pair[1]["qualification_allocation"]:
            raise _invalid("Paired qualification opportunity must be equal")
        legacy_arms = []
        for arm in pair:
            legacy = {key: value for key, value in arm.items() if key not in {"sample_id", "stage", "qualification_allocation"}}
            legacy["project_total"] = {key: arm["project_total"][key] - arm["qualification_allocation"][key] for key in total}
            legacy_arms.append(legacy)
        legacy = {**contract, "contract_version": "creative-experiment-budget.v1", "arms": legacy_arms}
        validate_comparison_budget(legacy, require_both_arms=True)
    if stages["PILOT"] != 2 or stages["EXPLORATION"] not in {0, 6}:
        raise _invalid("Paired samples must freeze two pilot and optionally six exploration tasks")
    if any(sum(arm["project_total"][key] for arm in arms) != total[key] for key in total):
        raise _invalid("Paired sample total must equal every frozen stage allocation including repair")
    return deepcopy(contract)


def budget_phases(plan: dict[str, Any]) -> tuple[str, ...]:
    if plan["contract_version"] == PAIRED_SAMPLES_VERSION:
        return PAIRED_SAMPLES_PHASES
    if plan["contract_version"] in PROVIDER_BUDGET_VERSIONS:
        return PROVIDER_CAMPAIGN_PHASES
    return SINGLE_BOOK_PHASES if plan["contract_version"] in SINGLE_BOOK_VERSIONS else PHASES


def allocation_fields(plan: dict[str, Any]) -> dict[str, str]:
    return {phase: phase.lower() + "_allocation" for phase in budget_phases(plan)}


def _validate_single_book_budget(contract: dict[str, Any], *, require_both_arms: bool) -> dict[str, Any]:
    if require_both_arms:
        raise _invalid("Single-book allocation cannot establish an A/B comparison")
    _text(contract["experiment_id"], "experiment_id")
    if contract["accounting_basis"] != "ACCOUNT_ENTITLEMENT":
        raise _invalid("Single-book stage budget requires ACCOUNT_ENTITLEMENT")
    shared = _allocation(contract["shared_total"], "shared_total", positive=True)
    arms = contract["arms"]
    if not isinstance(arms, list) or len(arms) != 1:
        raise _invalid("Single-book allocation requires exactly one SINGLE participant")
    fields = allocation_fields(contract)
    arm = _object(arms[0], "single-book allocation", {
        "arm", "project_id", "book_id", "project_total", "chapter_ranges", *fields.values(),
    })
    if arm["arm"] != "SINGLE":
        raise _invalid("Single-book allocation requires the SINGLE participant")
    for key in ("project_id", "book_id"):
        _text(arm[key], key)
    for key in ("project_total", *fields.values()):
        _allocation(arm[key], key)
    ranges = _object(arm["chapter_ranges"], "chapter_ranges", {"CREATION_EARLY", "CREATION_LATE"})
    for value in ranges.values():
        if (not isinstance(value, list) or len(value) != 2
            or any(type(number) is not int or number < 1 for number in value) or value[0] > value[1]):
            raise _invalid("Single-book chapter ranges require two ordered positive integer endpoints")
    if contract["contract_version"] == SINGLE_BOOK_VERSION:
        if ranges != {"CREATION_EARLY": [1, 6], "CREATION_LATE": [7, 12]}:
            raise _invalid("Single-book chapter ranges must remain exactly 1–6 and 7–12")
    else:
        if ranges["CREATION_EARLY"][0] != 1 or ranges["CREATION_LATE"][0] != ranges["CREATION_EARLY"][1] + 1:
            raise _invalid("Production chapter phases must partition one contiguous frozen range starting at chapter 1")
        previous = _object(contract["previous_policy"], "previous_policy", {"policy_version", "policy_hash", "contract_hash"})
        _text(previous["policy_version"], "previous policy version")
        if (not isinstance(previous["policy_hash"], str) or not re.fullmatch(r"[0-9a-f]{64}", previous["policy_hash"])
            or not isinstance(previous["contract_hash"], str) or not _HASH.fullmatch(previous["contract_hash"])):
            raise _invalid("Production reallocation requires exact native predecessor policy and contract hashes")
    for key in shared:
        if arm["project_total"][key] != sum(arm[field][key] for field in fields.values()):
            raise _invalid("Single-book project total must equal its frozen phase allocations")
        if arm["project_total"][key] != shared[key]:
            raise _invalid("Single-book shared total must equal its project allocation")
    return deepcopy(contract)


def arm_for_project(comparison_budget: dict[str, Any], project_id: str) -> dict[str, Any]:
    plan = validate_comparison_budget(comparison_budget)
    for arm in plan["arms"]:
        if arm["project_id"] == project_id:
            return arm
    raise KernelError("CREATIVE_BUDGET_SCOPE_MISMATCH", "project does not belong to the frozen experiment")


def contract_hash(comparison_budget: dict[str, Any]) -> str:
    plan = validate_comparison_budget(comparison_budget)
    encoded = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def validate_policy(value: Any) -> dict[str, Any]:
    policy = _object(value, "policy", {"policy_version", "comparison_budget", "authorization"})
    _text(policy["policy_version"], "policy_version")
    plan = validate_comparison_budget(policy["comparison_budget"])
    if plan["contract_version"] in PROVIDER_BUDGET_VERSIONS:
        return _validate_provider_campaign_policy(policy, plan)
    if plan["accounting_basis"] != "ACCOUNT_ENTITLEMENT":
        raise _invalid("Native stage budget requires ACCOUNT_ENTITLEMENT; PRICED needs an explicit monetary phase contract")
    authorization = _object(policy["authorization"], "authorization", {
        "authorization_ref", "evidence_hash", "project_id", "book_id", "authorized_cumulative_caps",
        *({"business_scope"} if plan["contract_version"] in SINGLE_BOOK_VERSIONS else set()),
    })
    for key in ("authorization_ref", "project_id", "book_id"):
        _text(authorization[key], key)
    digest = authorization["evidence_hash"]
    if not isinstance(digest, str) or not _HASH.fullmatch(digest):
        raise _invalid("Comparison authorization requires an exact evidence_hash")
    arm = arm_for_project(plan, authorization["project_id"])
    if authorization["book_id"] != arm["book_id"]:
        raise KernelError("CREATIVE_BUDGET_SCOPE_MISMATCH", "authorization scope differs from the frozen Book")
    fields = allocation_fields(plan)
    caps = _object(authorization["authorized_cumulative_caps"], "authorized cumulative caps", set(fields))
    for phase, cap in caps.items():
        amounts = _allocation(cap, "authorized " + phase, paired=False)
        if any(amounts[key] > arm[fields[phase]][key] for key in amounts):
            raise _invalid("Comparison authorization exceeds the immutable phase opportunity")
    if plan["contract_version"] in SINGLE_BOOK_VERSIONS:
        scope = _object(authorization["business_scope"], "business_scope", {"source_allowed", "design_allowed", "max_chapter_number"})
        if any(type(scope[key]) is not bool for key in ("source_allowed", "design_allowed")):
            raise _invalid("Single-book business permissions must be booleans")
        if _integer(scope["max_chapter_number"], "max_chapter_number") > arm["chapter_ranges"]["CREATION_LATE"][1]:
            raise _invalid("Single-book business scope cannot exceed its frozen chapter range")
    return deepcopy(policy)


def _monetary_allocation(value: Any, label: str, *, paired: bool = True) -> dict[str, Any]:
    result = _object(value, label, {"calls", "tokens", "priced_usd"})
    _allocation({key: result[key] for key in ("calls", "tokens")}, label, paired=paired)
    if not isinstance(result["priced_usd"], str) or not re.fullmatch(r"(0|[1-9][0-9]*)(\.[0-9]+)?", result["priced_usd"]):
        raise _invalid("priced USD requires a decimal string")
    try:
        amount = Decimal(result["priced_usd"])
    except ArithmeticError as exc:
        raise _invalid("priced USD is invalid") from exc
    if not amount.is_finite() or amount < 0 or (not result["calls"] and amount):
        raise _invalid("priced USD must be finite, non-negative and bound to calls")
    return result


def _validate_provider_campaign(value: dict[str, Any], *, require_both_arms: bool) -> dict[str, Any]:
    plan = _object(value, "provider campaign", {
        "contract_version", "experiment_id", "manifest_hash", "expires_at", "accounting_basis",
        "shared_total", "arms", "entitlements", *({"previous_policy"} if "previous_policy" in value else set()),
        *({"renewal"} if value["contract_version"] == PROVIDER_RENEWAL_VERSION else set()),
    })
    if "previous_policy" in plan:
        previous = _object(plan["previous_policy"], "previous_policy", {"policy_version", "policy_hash", "contract_hash"})
        _text(previous["policy_version"], "previous policy version")
        if (not isinstance(previous["policy_hash"], str) or not re.fullmatch(r"[0-9a-f]{64}", previous["policy_hash"])
            or not isinstance(previous["contract_hash"], str) or not _HASH.fullmatch(previous["contract_hash"])):
            raise _invalid("campaign monetary amendment requires exact predecessor hashes")
    if require_both_arms or plan["accounting_basis"] != "MIXED":
        raise _invalid("Provider campaign budget does not itself prove a paired comparison")
    _text(plan["experiment_id"], "experiment_id")
    if not isinstance(plan["manifest_hash"], str) or not _HASH.fullmatch(plan["manifest_hash"]):
        raise _invalid("Provider campaign requires its frozen manifest hash")
    try:
        if datetime.fromisoformat(plan["expires_at"]).tzinfo is None:
            raise ValueError("timezone required")
    except (ValueError, TypeError) as exc:
        raise _invalid("Provider campaign requires a timezone-aware expiry") from exc
    total = _monetary_allocation(plan["shared_total"], "shared_total")
    if not total["calls"] or not total["tokens"]:
        raise _invalid("Provider campaign requires a positive cumulative allowance")
    if not isinstance(plan["arms"], list) or len(plan["arms"]) != 1:
        raise _invalid("Provider campaign binds one project and one production Book")
    fields = allocation_fields(plan)
    arm = _object(plan["arms"][0], "campaign participant", {
        "arm", "project_id", "book_id", "project_total", "chapter_ranges", *fields.values(),
    })
    if arm["arm"] != "SINGLE":
        raise _invalid("Provider campaign requires the SINGLE participant")
    for key in ("project_id", "book_id"):
        _text(arm[key], key)
    for key in ("project_total", *fields.values()):
        _monetary_allocation(arm[key], key, paired=plan["contract_version"] != PROVIDER_RENEWAL_VERSION)
    ranges = _object(arm["chapter_ranges"], "chapter_ranges", {"PRODUCTION"})
    span = ranges["PRODUCTION"]
    if (not isinstance(span, list) or len(span) != 2 or span[0] != 1
        or any(type(number) is not int or number < 1 for number in span)):
        raise _invalid("Provider campaign binds a contiguous production range starting at chapter 1")
    if arm["project_total"] != total or any(
        Decimal(str(total[key])) != sum(Decimal(str(arm[field][key])) for field in fields.values())
        for key in total
    ):
        raise _invalid("Provider campaign totals must equal all phase allocations")
    if not isinstance(plan["entitlements"], list):
        raise _invalid("Provider campaign requires an explicit entitlement list")
    identities = set()
    for lane in plan["entitlements"]:
        lane = _object(lane, "entitlement", {"provider", "authorization_ref", "calls", "tokens"})
        identity = tuple(_text(lane[key], key) for key in ("provider", "authorization_ref"))
        if identity in identities:
            raise _invalid("Provider campaign entitlement identity is duplicated")
        identities.add(identity)
        for key in ("calls", "tokens"):
            if _integer(lane[key], "entitlement " + key, 0 if key == "tokens" and plan["contract_version"] == PROVIDER_RENEWAL_VERSION else 1) > total[key]:
                raise _invalid("entitlement allowance exceeds the complete campaign")
    if plan["contract_version"] == PROVIDER_RENEWAL_VERSION:
        from .creative_budget_renewal import validate_renewal_contract
        validate_renewal_contract(plan)
    return deepcopy(plan)


def _validate_provider_campaign_policy(policy: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    authorization = _object(policy["authorization"], "campaign authorization", {
        "authorization_ref", "evidence_hash", "project_id", "book_id", "authorized_cumulative_caps", "business_scope",
    })
    for key in ("authorization_ref", "project_id", "book_id"):
        _text(authorization[key], key)
    if not isinstance(authorization["evidence_hash"], str) or not _HASH.fullmatch(authorization["evidence_hash"]):
        raise _invalid("Provider campaign requires exact authorization evidence")
    arm = arm_for_project(plan, authorization["project_id"])
    if authorization["book_id"] != arm["book_id"]:
        raise _invalid("Provider campaign authorization must bind its production Book")
    caps = _object(authorization["authorized_cumulative_caps"], "campaign phase authorization", set(PROVIDER_CAMPAIGN_PHASES))
    for phase, cap in caps.items():
        _monetary_allocation(cap, phase, paired=plan["contract_version"] != PROVIDER_RENEWAL_VERSION)
        if any(Decimal(str(cap[key])) > Decimal(str(arm[phase.lower() + "_allocation"][key])) for key in cap):
            raise _invalid("phase authorization exceeds its frozen campaign allocation")
    scope = _object(authorization["business_scope"], "business_scope", {"source_allowed", "design_allowed", "max_chapter_number"})
    if any(type(scope[key]) is not bool for key in ("source_allowed", "design_allowed")):
        raise _invalid("Provider campaign business permissions require booleans")
    if _integer(scope["max_chapter_number"], "max_chapter_number") > arm["chapter_ranges"]["PRODUCTION"][1]:
        raise _invalid("Provider campaign authorization exceeds its production chapter range")
    return deepcopy(policy)


_SOURCE_CAPABILITIES = {
    "source.content.classify": "source.content.classify",
    "deconstruction.observe": "source.deconstruction.observe",
    "mkaos.knowledge.extract": "source.mkaos.extract",
    "mkaos.rule.extract": "source.mkaos.extract",
    "mkaos.template.extract": "source.mkaos.extract",
}
_SOURCE_OPERATIONS = {
    "source.import.document.profile": {"source.content.classify"},
    "source.import.deconstruction.execute": {"deconstruction.observe"},
    "source.import.mkaos.extract": {"mkaos.knowledge.extract", "mkaos.rule.extract", "mkaos.template.extract"},
    "source.import.reprocessing.apply": {"deconstruction.observe", "mkaos.knowledge.extract", "mkaos.rule.extract", "mkaos.template.extract"},
}
_CHAPTER_STAGES = {
    "chapter.memo.generate": "memo",
    "chapter.context.retrieve": "retrieval",
    "chapter.draft.generate": "draft",
    "chapter.review.evaluate": "review",
    "chapter.revision.apply": "revision",
    "chapter.revision.review": "rereview",
    "chapter.canon.extract": "canon_extraction",
    "chapter.canon.propose_changes": "canon_support",
    "chapter.quality.structural.evaluate": "quality_structural",
    "chapter.quality.commercial.evaluate": "quality_commercial",
    "chapter.quality.source_originality.evaluate": "quality_source_originality",
    "chapter.quality.longform.evaluate": "quality_longform",
    "chapter.quality.platform.evaluate": "quality_platform",
    "reader_outcome.evaluate": "reader_outcome",
    "longform.prose_review": "longform_prose_review",
    "screenplay_generate": "screenplay_generate",
    "screenplay_review": "screenplay_review",
    "screenplay_revision": "screenplay_revision",
    "story_design.semantic_evaluate": "narrative_semantic_evaluation",
}
_PLANNING_CAPABILITIES = {
    "creative.candidates.generate": "creative.proposal.generate",
    "theme.candidates.generate": "theme.question.generate",
    "ending.intent.generate": "ending.intent.generate",
    "reader.promise.generate": "reader.promise.generate",
    "world.design.generate": "world.design.generate",
    "character.cast.generate": "character.cast.generate",
    "book_plan.generate": "planning.book.generate",
    "volume_plan.generate": "planning.volume.generate",
    "arc_plan.generate": "planning.arc.generate",
    "chapter_group_plan.generate": "planning.chapter_group.generate",
    "chapter_plan.generate": "planning.story_chapter.generate",
}


def classify_phase(operation_name: str, capability: str, request_payload: dict[str, Any], attempt_no: int) -> str:
    failure = KernelError("CREATIVE_BUDGET_PHASE_UNKNOWN", "Provider effect operation, capability, frozen stage or attempt is unknown or inconsistent")
    if not isinstance(operation_name, str) or not isinstance(capability, str) or not isinstance(request_payload, dict):
        raise failure
    if type(attempt_no) is not int or attempt_no < 1:
        raise failure
    stage = request_payload.get("stage")
    inputs = request_payload.get("input")
    if not isinstance(stage, str) or not isinstance(inputs, dict):
        raise failure
    if capability in _SOURCE_OPERATIONS.get(operation_name, set()):
        if stage != _SOURCE_CAPABILITIES[capability]:
            raise failure
        return "SOURCE"
    if operation_name == "provider.qualification.d0" and capability in _SOURCE_CAPABILITIES:
        if stage != "d0_qualification":
            raise failure
        return "SOURCE"
    expected_stage = _CHAPTER_STAGES.get(operation_name)
    if expected_stage:
        if stage != expected_stage or capability != "model." + expected_stage:
            raise failure
        return "REPAIR" if attempt_no > 1 or stage in {"revision", "rereview", "screenplay_revision"} else "CREATION"
    if operation_name == "story_planning.generate":
        if stage in {"world_candidates.generate", "world_candidates.evaluate", "world_candidates.actor_0", "world_candidates.actor_1", "world_candidates.actor_2"}:
            if capability != "planning.story_chapter.generate" or not isinstance(inputs.get("world_preparation"), dict):
                raise failure
            return "REPAIR" if attempt_no > 1 else "CREATION"
        if capability != _PLANNING_CAPABILITIES.get(stage):
            raise failure
        command = inputs.get("planning_command")
        if not isinstance(command, dict):
            raise failure
        repair = command.get("repair_number")
        if type(repair) is not int or repair < 0:
            raise failure
        return "REPAIR" if repair > 0 or attempt_no > 1 else "CREATION"
    raise failure


__all__ = ["PAIRED_SAMPLES_VERSION", "PAIRED_SAMPLES_PHASES", "V5_POLICY_SCHEMA", "PHASES", "POLICY_SCHEMA", "SINGLE_BOOK_PHASES", "SINGLE_BOOK_VERSION", "SINGLE_BOOK_VERSIONS", "PRODUCTION_BOOK_VERSION", "PROVIDER_CAMPAIGN_VERSION", "PROVIDER_CAMPAIGN_PHASES", "V1_POLICY_SCHEMA", "V2_POLICY_SCHEMA", "V3_POLICY_SCHEMA", "V4_POLICY_SCHEMA", "allocation_fields", "arm_for_project", "budget_phases", "classify_phase", "contract_hash", "validate_comparison_budget", "validate_policy"]
