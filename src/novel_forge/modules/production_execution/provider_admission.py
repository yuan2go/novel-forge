from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Any, Mapping

from .token_meter import SYSTEM_CONTEXT_LIMIT, TOKENIZER_METHODS, count_text, measure_input


PROVIDER_ADMISSION_CONTRACT_VERSION = "provider-token-admission-v1"
SHARED_PROVIDER_MONEY_CAP_ENVIRONMENT = (
    ("project_daily", "NOVEL_FORGE_PROJECT_DAILY_PROVIDER_CAP"),
    ("project_total", "NOVEL_FORGE_PROJECT_TOTAL_PROVIDER_CAP"),
    ("operation_total", "NOVEL_FORGE_OPERATION_PROVIDER_CAP"),
    ("provider_project_daily", "NOVEL_FORGE_PROVIDER_DAILY_CAP"),
    ("global_daily", "NOVEL_FORGE_DAILY_PROVIDER_CAP"),
    ("global_total", "NOVEL_FORGE_GLOBAL_PROVIDER_CAP"),
    ("global_monthly", "NOVEL_FORGE_GLOBAL_MONTHLY_PROVIDER_CAP"),
    ("work_total", "NOVEL_FORGE_WORK_PROVIDER_CAP"),
    ("model_project_total", "NOVEL_FORGE_MODEL_PROJECT_CAP"),
)
_SUPPORTED_METHODS = {
    "DEEPSEEK_UTF8_BYTES_UPPER_BOUND_V1": ("deepseek", "PROVEN_UPPER_BOUND"),
    "OPENAI_UTF8_BYTES_UPPER_BOUND_V1": ("openai", "PROVEN_UPPER_BOUND"),
    "SCRIPTED_UTF8_BYTES_EXACT_V1": ("scripted_provider_v2", "EXACT"),
    "CODEX_CLI_APPLICATION_UTF8_BYTES_UPPER_BOUND_V1": (
        "codex-cli",
        "APPLICATION_VISIBLE_UPPER_BOUND",
    ),
}
_SCRIPTED_PROVIDER_CONTEXT_BYTES = 262_144
_REQUIRED_COMPLETE_COVERAGE = frozenset(
    {
        "system_runtime_instructions",
        "prompt_template",
        "skill_instructions",
        "tool_policy_and_schemas",
        "structured_output_schema",
        "request_envelope_and_framing",
        "output_reserve",
        "safety_margin",
    }
)


DEEPSEEK_STRICT_PROTOCOL = "deepseek-chat-completions-strict-tool-v1"
DEEPSEEK_OUTPUT_TOOL = "submit_structured_result"


def provider_request_protocol(provider: str, *, output_mode: str = "") -> str:
    if output_mode and (provider != "deepseek" or output_mode != "STRICT_TOOL_V1"):
        raise ValueError("PROVIDER_OUTPUT_MODE_UNSUPPORTED")
    if provider == "deepseek":
        return (
            DEEPSEEK_STRICT_PROTOCOL
            if output_mode
            else "deepseek-chat-completions-json-v1"
        )
    if provider == "openai":
        return "openai-responses-text-envelope-v1"
    if provider == "scripted_provider_v2":
        return "scripted-responses-text-envelope-v1"
    if provider == "codex-cli":
        return "codex-cli-application-stdin-v1"
    return "unsupported-provider-envelope-v1"


def deepseek_strict_tools(output_schema_json: str) -> list[dict[str, Any]]:
    schema = json.loads(output_schema_json)
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ValueError("DEEPSEEK_STRICT_ROOT_OBJECT_REQUIRED")

    def project(node: Any) -> dict[str, Any]:
        if not isinstance(node, dict):
            raise ValueError("DEEPSEEK_STRICT_SCHEMA_UNSUPPORTED")
        native_only = {
            "minLength",
            "maxLength",
            "minItems",
            "maxItems",
            "$schema",
            "title",
        }
        supported = {
            "type",
            "properties",
            "required",
            "additionalProperties",
            "items",
            "enum",
            "description",
        }
        if set(node) - native_only - supported:
            raise ValueError("DEEPSEEK_STRICT_SCHEMA_UNSUPPORTED")
        kind = node.get("type")
        if kind not in {"object", "array", "string", "number", "integer", "boolean"}:
            raise ValueError("DEEPSEEK_STRICT_SCHEMA_UNSUPPORTED")
        result = {k: v for k, v in node.items() if k in supported}
        if kind == "object":
            properties = node.get("properties")
            if (
                not isinstance(properties, dict)
                or set(node.get("required") or []) != set(properties)
                or node.get("additionalProperties") is not False
            ):
                raise ValueError("DEEPSEEK_STRICT_CLOSED_REQUIRED_OBJECT_ONLY")
            result["properties"] = {k: project(v) for k, v in properties.items()}
        elif kind == "array":
            result["items"] = project(node.get("items"))
        return result

    return [
        {
            "type": "function",
            "function": {
                "name": DEEPSEEK_OUTPUT_TOOL,
                "description": "Submit the complete task result once. All frozen business constraints still apply.",
                "strict": True,
                "parameters": project(schema),
            },
        }
    ]


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ProviderRequestEnvelope:
    provider: str
    model: str
    protocol: str
    input_text: str
    max_output_tokens: int
    timeout_seconds: int
    stable_idempotency_key: str
    reasoning_effort: str = ""
    pricing_policy_json: str = ""
    output_schema_json: str = ""

    def __post_init__(self) -> None:
        if not all(
            str(value).strip()
            for value in (
                self.provider,
                self.model,
                self.protocol,
                self.input_text,
                self.stable_idempotency_key,
            )
        ):
            raise ValueError("Provider request envelope is incomplete")
        if self.max_output_tokens <= 0 or self.timeout_seconds <= 0:
            raise ValueError("Provider request envelope limits must be positive")

        if self.protocol == DEEPSEEK_STRICT_PROTOCOL:
            if self.provider != "deepseek" or not self.output_schema_json:
                raise ValueError("DEEPSEEK_STRICT_SCHEMA_REQUIRED")
            deepseek_strict_tools(self.output_schema_json)
        elif self.output_schema_json:
            raise ValueError("PROVIDER_OUTPUT_SCHEMA_PROTOCOL_MISMATCH")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if not self.reasoning_effort:
            payload.pop("reasoning_effort")
        if not self.pricing_policy_json:
            payload.pop("pricing_policy_json")
        if not self.output_schema_json:
            payload.pop("output_schema_json")
        return payload

    @property
    def input_text_hash(self) -> str:
        return "sha256:" + hashlib.sha256(self.input_text.encode("utf-8")).hexdigest()

    def to_identity_dict(self) -> dict[str, Any]:
        return {
            **(
                {"reasoning_effort": self.reasoning_effort}
                if self.reasoning_effort
                else {}
            ),
            **(
                {"pricing_policy_json": self.pricing_policy_json}
                if self.pricing_policy_json
                else {}
            ),
            **(
                {"output_schema_json": self.output_schema_json}
                if self.output_schema_json
                else {}
            ),
            "provider": self.provider,
            "model": self.model,
            "protocol": self.protocol,
            "input_text_hash": self.input_text_hash,
            "max_output_tokens": self.max_output_tokens,
            "timeout_seconds": self.timeout_seconds,
            "stable_idempotency_key": self.stable_idempotency_key,
        }

    @property
    def envelope_hash(self) -> str:
        return _hash(self.to_identity_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProviderRequestEnvelope":
        return cls(
            pricing_policy_json=str(payload.get("pricing_policy_json") or ""),
            output_schema_json=str(payload.get("output_schema_json") or ""),
            reasoning_effort=str(payload.get("reasoning_effort") or ""),
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("model") or ""),
            protocol=str(payload.get("protocol") or ""),
            input_text=str(payload.get("input_text") or ""),
            max_output_tokens=int(payload.get("max_output_tokens") or 0),
            timeout_seconds=int(payload.get("timeout_seconds") or 0),
            stable_idempotency_key=str(payload.get("stable_idempotency_key") or ""),
        )

    @classmethod
    def from_identity_dict(
        cls, payload: Mapping[str, Any], *, input_text: str
    ) -> "ProviderRequestEnvelope":
        envelope = cls(
            pricing_policy_json=str(payload.get("pricing_policy_json") or ""),
            output_schema_json=str(payload.get("output_schema_json") or ""),
            reasoning_effort=str(payload.get("reasoning_effort") or ""),
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("model") or ""),
            protocol=str(payload.get("protocol") or ""),
            input_text=input_text,
            max_output_tokens=int(payload.get("max_output_tokens") or 0),
            timeout_seconds=int(payload.get("timeout_seconds") or 0),
            stable_idempotency_key=str(payload.get("stable_idempotency_key") or ""),
        )
        if envelope.input_text_hash != str(payload.get("input_text_hash") or ""):
            raise ValueError("PROVIDER_REQUEST_IDENTITY_DRIFT: input hash changed")
        return envelope


@dataclass(frozen=True, slots=True)
class TokenAccountingContract:
    provider: str
    model: str
    route_identity: str
    meter_identity: str
    meter_version: str
    accounting_method: str
    precision: str
    evidence_ref: str
    serialization_contract: str
    model_context_limit: int
    output_reserve: int
    safety_margin: int
    framing_overhead: int
    execution_token_limit: int = 0
    contract_version: str = "provider-token-accounting-v3"

    def __post_init__(self) -> None:
        if not all(
            str(value).strip()
            for value in (
                self.provider,
                self.model,
                self.route_identity,
                self.meter_identity,
                self.meter_version,
                self.accounting_method,
                self.precision,
                self.serialization_contract,
                self.contract_version,
            )
        ):
            raise ValueError("TokenAccountingContract is incomplete")
        if self.contract_version not in {
            "provider-token-accounting-v1",
            "provider-token-accounting-v2",
            "provider-token-accounting-v3",
            "provider-token-accounting-v4",
        }:
            raise ValueError("TokenAccountingContract version is unsupported")
        if (
            self.contract_version == "provider-token-accounting-v1"
            and self.execution_token_limit == 0
        ):
            object.__setattr__(self, "execution_token_limit", self.model_context_limit)
        if (
            self.contract_version in {"provider-token-accounting-v2", "provider-token-accounting-v3", "provider-token-accounting-v4"}
            and self.execution_token_limit <= 0
        ):
            raise ValueError(
                "TokenAccountingContract v2 requires an execution token limit"
            )
        if (
            min(
                self.model_context_limit,
                self.execution_token_limit,
                self.output_reserve,
                self.safety_margin,
                self.framing_overhead,
            )
            < 0
            or self.model_context_limit <= 0
        ):
            raise ValueError("TokenAccountingContract limits are invalid")
        if (
            self.precision
            in {
                "EXACT",
                "PROVEN_UPPER_BOUND",
                "APPLICATION_VISIBLE_UPPER_BOUND",
            }
            and not self.evidence_ref
        ):
            raise ValueError("proven TokenAccountingContract requires evidence")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TokenAccountingContract":
        return cls(
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("model") or ""),
            route_identity=str(payload.get("route_identity") or ""),
            meter_identity=str(payload.get("meter_identity") or ""),
            meter_version=str(payload.get("meter_version") or ""),
            accounting_method=str(payload.get("accounting_method") or ""),
            precision=str(payload.get("precision") or ""),
            evidence_ref=str(payload.get("evidence_ref") or ""),
            serialization_contract=str(payload.get("serialization_contract") or ""),
            model_context_limit=int(payload.get("model_context_limit") or 0),
            execution_token_limit=int(
                payload.get("execution_token_limit")
                or payload.get("model_context_limit")
                or 0
            ),
            output_reserve=int(payload.get("output_reserve") or 0),
            safety_margin=int(payload.get("safety_margin") or 0),
            framing_overhead=int(payload.get("framing_overhead") or 0),
            contract_version=str(
                payload.get("contract_version") or "provider-token-accounting-v1"
            ),
        )


@dataclass(frozen=True, slots=True)
class ProviderAdmissionReceipt:
    status: str
    reason: str
    precision: str
    envelope_hash: str
    accounting_contract: Mapping[str, Any]
    component_usage: Mapping[str, int]
    total_reserved: int
    applicable_limit: int
    context_bundle_tokens: int
    context_bundle_status: str
    input_component_hashes: Mapping[str, str] = field(default_factory=dict)
    complete_request_coverage: tuple[str, ...] = ()
    contract_version: str = PROVIDER_ADMISSION_CONTRACT_VERSION
    measurement: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            **({"measurement": dict(self.measurement)} if self.measurement else {}),
            "contract_version": self.contract_version,
            "status": self.status,
            "reason": self.reason,
            "precision": self.precision,
            "envelope_hash": self.envelope_hash,
            "accounting_contract": dict(self.accounting_contract),
            "component_usage": dict(self.component_usage),
            "total_reserved": self.total_reserved,
            "applicable_limit": self.applicable_limit,
            "context_bundle_tokens": self.context_bundle_tokens,
            "context_bundle_status": self.context_bundle_status,
            "input_component_hashes": dict(self.input_component_hashes),
            "complete_request_coverage": list(self.complete_request_coverage),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProviderAdmissionReceipt":
        return cls(
            measurement=dict(payload.get("measurement") or {}),
            status=str(payload.get("status") or ""),
            reason=str(payload.get("reason") or ""),
            precision=str(payload.get("precision") or ""),
            envelope_hash=str(payload.get("envelope_hash") or ""),
            accounting_contract=dict(payload.get("accounting_contract") or {}),
            component_usage={
                str(key): int(value)
                for key, value in dict(payload.get("component_usage") or {}).items()
            },
            total_reserved=int(payload.get("total_reserved") or 0),
            applicable_limit=int(payload.get("applicable_limit") or 0),
            context_bundle_tokens=int(payload.get("context_bundle_tokens") or 0),
            context_bundle_status=str(payload.get("context_bundle_status") or ""),
            input_component_hashes={
                str(key): str(value)
                for key, value in dict(
                    payload.get("input_component_hashes") or {}
                ).items()
            },
            complete_request_coverage=tuple(
                str(value) for value in payload.get("complete_request_coverage") or ()
            ),
            contract_version=str(
                payload.get("contract_version") or PROVIDER_ADMISSION_CONTRACT_VERSION
            ),
        )


def build_route_token_accounting_contract(
    *,
    provider: str,
    model: str,
    route_identity: str,
    accounting_method: str,
    accounting_evidence_ref: str,
    model_context_limit: int,
    execution_token_limit: int = 0,
    output_reserve: int,
    safety_margin: int,
    framing_overhead: int,
    serialization_contract: str = "",
    contract_version: str = "provider-token-accounting-v3",
) -> TokenAccountingContract:
    if accounting_method in TOKENIZER_METHODS and provider in {"openai", "deepseek", "codex-cli"} and accounting_evidence_ref and model_context_limit > 0:
        method = accounting_method
        precision = "APPLICATION_VISIBLE_ESTIMATE" if provider == "codex-cli" else "TOKENIZER_ESTIMATE"
        evidence_ref = accounting_evidence_ref
        context_limit = model_context_limit
    elif provider == "scripted_provider_v2" and not accounting_method:
        method = "SCRIPTED_UTF8_BYTES_EXACT_V1"
        precision = "EXACT"
        evidence_ref = "fixture-protocol:scripted-byte-meter:v1"
        context_limit = model_context_limit or (512_000 if contract_version == "provider-token-accounting-v4" else _SCRIPTED_PROVIDER_CONTEXT_BYTES)
    elif (
        (
            (
                provider == "openai"
                and accounting_method == "OPENAI_UTF8_BYTES_UPPER_BOUND_V1"
            )
            or (
                provider == "deepseek"
                and accounting_method == "DEEPSEEK_UTF8_BYTES_UPPER_BOUND_V1"
            )
        )
        and model_context_limit > 0
        and accounting_evidence_ref
    ):
        method = accounting_method
        precision = "PROVEN_UPPER_BOUND"
        evidence_ref = accounting_evidence_ref
        context_limit = model_context_limit
    elif (
        provider == "codex-cli"
        and accounting_method == "CODEX_CLI_APPLICATION_UTF8_BYTES_UPPER_BOUND_V1"
        and model_context_limit > 0
        and accounting_evidence_ref
    ):
        method = accounting_method
        precision = "APPLICATION_VISIBLE_UPPER_BOUND"
        evidence_ref = accounting_evidence_ref
        context_limit = model_context_limit
    else:
        method = accounting_method or "UNSUPPORTED"
        precision = "UNPROVEN"
        evidence_ref = ""
        context_limit = max(1, model_context_limit)
    return TokenAccountingContract(
        provider=provider,
        model=model,
        route_identity=route_identity,
        meter_identity=(
            "deepseek-byte-token-upper-bound"
            if provider == "deepseek"
            else "openai-byte-token-upper-bound"
            if provider == "openai"
            else "codex-cli-application-stdin-byte-upper-bound"
            if provider == "codex-cli"
            else "scripted-byte-token-meter"
            if provider == "scripted_provider_v2"
            else "unavailable-provider-meter"
        ),
        meter_version="v1",
        accounting_method=method,
        precision=precision,
        evidence_ref=evidence_ref,
        serialization_contract=serialization_contract
        or provider_request_protocol(provider),
        model_context_limit=context_limit,
        execution_token_limit=execution_token_limit or context_limit,
        output_reserve=output_reserve,
        safety_margin=safety_margin,
        framing_overhead=framing_overhead,
        contract_version=contract_version,
    )


def provider_request_token_components(
    input_text: str,
    *,
    output_reserve: int,
    safety_margin: int,
    framing_overhead: int,
    output_schema_json: str = "",
    accounting_method: str = "",
    model: str = "",
    accounting_evidence_ref: str = "",
) -> dict[str, int]:
    if (
        any(
            type(value) is not int or value < 0
            for value in (output_reserve, safety_margin, framing_overhead)
        )
        or output_reserve == 0
    ):
        raise ValueError("PROVIDER_TOKEN_COMPONENT_LIMIT_INVALID")
    return {
        "provider_input": count_text(input_text, method=accounting_method, model=model, evidence_ref=accounting_evidence_ref),
        **(
            {
                "structured_output_transport": count_text(
                    _canonical(
                        {
                            "tools": deepseek_strict_tools(output_schema_json),
                        }
                    ), method=accounting_method, model=model, evidence_ref=accounting_evidence_ref,
                )
            }
            if output_schema_json
            else {}
        ),
        "request_framing": framing_overhead,
        "output_reserve": output_reserve,
        "safety_margin": safety_margin,
    }


def prepare_provider_admission(
    envelope: ProviderRequestEnvelope,
    contract: TokenAccountingContract,
    *,
    context_bundle_tokens: int = 0,
    input_component_hashes: Mapping[str, str] | None = None,
    complete_request_coverage: tuple[str, ...] = (),
) -> ProviderAdmissionReceipt:
    reason = (
        "ADMITTED_APPLICATION_VISIBLE_ONLY"
        if contract.precision == "APPLICATION_VISIBLE_UPPER_BOUND"
        else "ADMITTED"
    )
    status = "ADMITTED"
    current = contract.contract_version == "provider-token-accounting-v4"
    tokenizer = current and contract.accounting_method in TOKENIZER_METHODS
    supported = (contract.provider, "APPLICATION_VISIBLE_ESTIMATE" if contract.provider == "codex-cli" else "TOKENIZER_ESTIMATE") if tokenizer else _SUPPORTED_METHODS.get(contract.accounting_method)
    coverage = frozenset(complete_request_coverage)
    if (
        contract.provider != envelope.provider
        or contract.model != envelope.model
        or contract.serialization_contract != envelope.protocol
    ):
        status, reason = "REJECTED", "TOKEN_ACCOUNTING_ROUTE_MISMATCH"
    elif supported != (
        contract.provider,
        contract.precision,
    ) or contract.precision not in {
        "EXACT",
        "PROVEN_UPPER_BOUND",
        "APPLICATION_VISIBLE_UPPER_BOUND",
        "APPLICATION_VISIBLE_ESTIMATE",
        "TOKENIZER_ESTIMATE",
    }:
        status, reason = "REJECTED", "TOKEN_ACCOUNTING_UNPROVEN"
    elif envelope.max_output_tokens != contract.output_reserve:
        status, reason = "REJECTED", "OUTPUT_RESERVE_MISMATCH"
    elif contract.contract_version in {"provider-token-accounting-v2", "provider-token-accounting-v3", "provider-token-accounting-v4"} and (
        not _REQUIRED_COMPLETE_COVERAGE.issubset(coverage)
        or not coverage.intersection({"context_bundle", "source_analysis_input"})
    ):
        status, reason = "REJECTED", "PROVIDER_REQUEST_COVERAGE_INCOMPLETE"
    components = provider_request_token_components(
        envelope.input_text,
        output_reserve=contract.output_reserve,
        output_schema_json=envelope.output_schema_json,
        safety_margin=contract.safety_margin,
        framing_overhead=contract.framing_overhead,
        accounting_method=contract.accounting_method if current else "",
        model=contract.model,
        accounting_evidence_ref=contract.evidence_ref,
    )
    total = sum(components.values())
    applicable_limit = min(SYSTEM_CONTEXT_LIMIT, contract.model_context_limit, contract.execution_token_limit) if current else contract.model_context_limit
    if status == "ADMITTED" and total > applicable_limit:
        status, reason = (
            "REJECTED",
            "PROVIDER_CONTEXT_CAPACITY_UNCERTAIN" if current and "UPPER_BOUND" in contract.accounting_method else "PROVIDER_CONTEXT_LIMIT_EXCEEDED",
        )
    return ProviderAdmissionReceipt(
        status=status,
        reason=reason,
        precision=contract.precision,
        envelope_hash=envelope.envelope_hash,
        accounting_contract=contract.to_dict(),
        component_usage=components,
        total_reserved=total,
        applicable_limit=applicable_limit,
        context_bundle_tokens=max(0, int(context_bundle_tokens)),
        context_bundle_status=("VALID" if context_bundle_tokens >= 0 else "INVALID"),
        input_component_hashes=dict(input_component_hashes or {}),
        complete_request_coverage=tuple(complete_request_coverage),
        measurement={**measure_input(envelope.input_text, method=contract.accounting_method,
                     model=contract.model, evidence_ref=contract.evidence_ref),
                     "protocol_framing_tokens_estimate": contract.framing_overhead,
                     "system_context_limit": SYSTEM_CONTEXT_LIMIT} if current else {},
    )


def verify_provider_admission(
    envelope: ProviderRequestEnvelope,
    receipt: ProviderAdmissionReceipt,
) -> None:
    if receipt.status != "ADMITTED":
        raise ValueError("PROVIDER_ADMISSION_REJECTED: " + receipt.reason)
    if receipt.envelope_hash != envelope.envelope_hash:
        raise ValueError("PROVIDER_REQUEST_IDENTITY_DRIFT: envelope hash changed")
    contract = TokenAccountingContract.from_dict(receipt.accounting_contract)
    replayed = prepare_provider_admission(
        envelope,
        contract,
        context_bundle_tokens=receipt.context_bundle_tokens,
        input_component_hashes=receipt.input_component_hashes,
        complete_request_coverage=receipt.complete_request_coverage,
    )
    if replayed.to_dict() != receipt.to_dict():
        raise ValueError("PROVIDER_REQUEST_IDENTITY_DRIFT: admission replay changed")


__all__ = [
    "PROVIDER_ADMISSION_CONTRACT_VERSION",
    "build_route_token_accounting_contract",
    "ProviderAdmissionReceipt",
    "ProviderRequestEnvelope",
    "TokenAccountingContract",
    "provider_request_protocol",
    "prepare_provider_admission",
    "provider_request_token_components",
    "verify_provider_admission",
]
