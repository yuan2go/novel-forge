from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Mapping


CODEX_INPUT_ONLY_OVERRIDES = (
    'web_search="disabled"',
    "tools.view_image=false",
    "features.view_image=false",
    "project_doc_max_bytes=0",
    "features.shell_tool=false",
    "features.shell_snapshot=false",
    "features.apps=false",
    "features.plugins=false",
    "features.browser_use=false",
    "features.computer_use=false",
    "features.image_generation=false",
    "features.multi_agent=false",
    "features.memories=false",
    "features.hooks=false",
    "features.goals=false",
    "features.code_mode=false",
    "features.workspace_dependencies=false",
    "features.skill_mcp_dependency_install=false",
    "features.skip_host_skill_discovery=true",
)


CODEX_SCHEMA_PROJECTION_VERSION = "codex-structured-schema.v3"
CODEX_NULLABLE_SHARED_TYPES_VERSION = "codex-nullable-shared-types.v1"
CODEX_NO_RETRY_POLICY = "codex-no-transport-retry.v1"


def codex_retry_overrides(policy: str = "") -> tuple[str, ...]:
    if not policy:
        return ()
    if policy != CODEX_NO_RETRY_POLICY:
        raise ValueError("unsupported frozen Codex transport retry policy")
    return (
        'model_provider="novel_forge_openai_no_retry"',
        'model_providers.novel_forge_openai_no_retry.name="OpenAI"',
        'model_providers.novel_forge_openai_no_retry.wire_api="responses"',
        "model_providers.novel_forge_openai_no_retry.requires_openai_auth=true",
        "model_providers.novel_forge_openai_no_retry.request_max_retries=0",
        "model_providers.novel_forge_openai_no_retry.stream_max_retries=0",
    )


def codex_local_binding_hash(*, codex_home: str, executable: str, entitlement: Mapping[str, str] | None, retry_policy: str = "") -> str:
    binding = {
        "codex_home": codex_home,
        "executable": executable,
        "entitlement": dict(entitlement) if entitlement is not None else None,
        "input_only_overrides": CODEX_INPUT_ONLY_OVERRIDES,
        "schema_projection": CODEX_SCHEMA_PROJECTION_VERSION,
    }
    overrides = codex_retry_overrides(retry_policy)
    if overrides:
        binding.update(retry_policy=retry_policy, retry_overrides=overrides)
    return hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()


def codex_account_binding_evidence(backend: object) -> dict:
    from .backends import CodexCliExecutionBackend

    if not isinstance(backend, CodexCliExecutionBackend) or backend.account_entitlement is None:
        raise ValueError("existing native Codex account-entitlement backend required")
    evidence = {
        "codex_home": backend.codex_home,
        "executable": backend.codex_executable,
        "entitlement": backend.account_entitlement.to_dict(),
    }
    if backend.retry_policy:
        evidence["retry_policy"] = backend.retry_policy
    return evidence


def codex_output_schema(schema: dict) -> dict:
    result = {k: v for k, v in schema.items() if k != "uniqueItems"}
    if set(result.get("properties", {})) == {"finding_code", "statement", "evidence_span_ids", "input_observation_asset_version_ids"}:
        properties = result["properties"]
        for key in ("anyOf", "oneOf"):
            if isinstance(result.get(key), list):
                result[key] = [
                    {**branch, "type": "object", "properties": {
                        **properties, **{name: {**properties.get(name, {}), **value}
                        for name, value in branch.get("properties", {}).items()},
                        **{name: {**properties[name], "maxItems": 0}
                        for name in ("evidence_span_ids", "input_observation_asset_version_ids")
                        if name not in branch.get("required", [])}},
                     "additionalProperties": False}
                    if "properties" in branch and "type" not in branch else branch
                    for branch in result[key]
                ]
        result["type"] = "object"
        result["additionalProperties"] = False
        result["required"] = list(properties)
    choices = [result["const"]] if "const" in result else result.get("enum", [])
    if "type" not in result and choices:
        types = {type(value) for value in choices}
        primitive_types = {str: "string", bool: "boolean", int: "integer", float: "number", type(None): "null"}
        if not types <= primitive_types.keys():
            raise ValueError("Codex enum/const requires explicit non-primitive Schema types")
        inferred = sorted(primitive_types[t] for t in types)
        result["type"] = inferred[0] if len(inferred) == 1 else inferred
    for key in ("properties", "$defs", "definitions", "patternProperties"):
        if isinstance(result.get(key), dict):
            result[key] = {k: codex_output_schema(v) for k, v in result[key].items()}
    for key in ("items", "additionalProperties", "not", "if", "then", "else"):
        if isinstance(result.get(key), dict):
            result[key] = codex_output_schema(result[key])
    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        if isinstance(result.get(key), list):
            result[key] = [codex_output_schema(v) for v in result[key]]
    if isinstance(result.get("type"), list) and set(result["type"]) == {"object", "null"}:
        result = {"anyOf": [{**result, "type": "object"}, {"type": "null"}]}
    return result


def require_codex_home(value: str) -> str:
    path = Path(value)
    if not value or not path.is_absolute() or not path.is_dir():
        raise ValueError("controlled Codex requires an explicit existing CODEX_HOME")
    return str(path.resolve())


def inspect_local_codex(values: Mapping[str, str] | None = None) -> dict:
    from .backends import observe_codex_cli_version

    values = os.environ if values is None else values
    executable = str(values.get("NOVEL_FORGE_CODEX_EXECUTABLE") or "")
    workspace = str(values.get("NOVEL_FORGE_CODEX_WORKSPACE") or "")
    blockers = []
    identity = {}
    try:
        version = observe_codex_cli_version(executable, working_directory=workspace)
        with Path(executable).open("rb") as stream:
            digest = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
        identity.update(
            executable=executable, cli_version=version, executable_sha256=digest
        )
        for name, observed in (("CLI_VERSION", version), ("EXECUTABLE_SHA256", digest)):
            expected = values.get("NOVEL_FORGE_CODEX_" + name)
            if expected and expected != observed:
                blockers.append("CODEX_" + name + "_DRIFT")
        if any(Path(workspace).iterdir()):
            blockers.append("CODEX_WORKSPACE_NOT_EMPTY")
    except (OSError, RuntimeError, ValueError):
        blockers.append("CODEX_LOCAL_PROCESS_UNAVAILABLE")
    try:
        identity["codex_home"] = require_codex_home(
            str(values.get("NOVEL_FORGE_CODEX_HOME") or "")
        )
    except ValueError:
        blockers.append("CODEX_HOME_NOT_EXPLICIT")
    execution_root = str(values.get("NOVEL_FORGE_CODEX_EXECUTION_ROOT") or "")
    if not execution_root or not Path(execution_root).is_absolute():
        blockers.append("CODEX_EXECUTION_ROOT_NOT_ABSOLUTE")
    required = (
        "NOVEL_FORGE_CODEX_CLI_VERSION",
        "NOVEL_FORGE_CODEX_EXECUTABLE_SHA256",
        "NOVEL_FORGE_PROVIDER_AUTH_PROFILE",
        "NOVEL_FORGE_PROVIDER_TOKEN_ACCOUNTING_METHOD",
        "NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF",
        "NOVEL_FORGE_CODEX_ACCOUNT_IDENTITY_REF",
        "NOVEL_FORGE_CODEX_CONFIGURATION_REF",
        "NOVEL_FORGE_QUALITY_MODEL",
        "NOVEL_FORGE_PROVIDER_MODEL_CONTEXT_LIMIT",
        "NOVEL_FORGE_PROVIDER_TOKEN_ACCOUNTING_EVIDENCE_REF",
        "NOVEL_FORGE_PROJECT_PROVIDER_CALL_LIMIT",
        "NOVEL_FORGE_PROJECT_PROVIDER_TOKEN_LIMIT",
    )
    membership = values.get("NOVEL_FORGE_RESOURCE_CONTROL_VERSION") == "billing-channel-resources.v1"
    if membership:
        required = tuple(name for name in required if name not in {
            "NOVEL_FORGE_PROJECT_PROVIDER_CALL_LIMIT", "NOVEL_FORGE_PROJECT_PROVIDER_TOKEN_LIMIT",
            "NOVEL_FORGE_QUALITY_MODEL"})
        try:
            from .membership_identity import observe_membership_identity
            observed = observe_membership_identity(str(values.get("NOVEL_FORGE_CODEX_HOME") or ""))
            identity["billing_identity"] = observed
            if observed["account_ref"] != values.get("NOVEL_FORGE_CODEX_ACCOUNT_IDENTITY_REF"):
                blockers.append("CODEX_MEMBERSHIP_IDENTITY_DRIFT")
        except ValueError as error:
            blockers.append(str(error))
    missing = [name for name in required if not str(values.get(name) or "").strip()]
    retry_policy = str(values.get("NOVEL_FORGE_CODEX_RETRY_POLICY") or "")
    try:
        retry_overrides = codex_retry_overrides(retry_policy)
    except ValueError:
        retry_overrides = ()
        blockers.append("CODEX_RETRY_POLICY_UNSUPPORTED")
    return {
        "state": "BLOCKED" if blockers else "LOCAL_PROCESS_VERIFIED",
        "identity": identity,
        "blockers": blockers,
        "missing_configuration": missing,
        "invocation_overrides": [*CODEX_INPUT_ONLY_OVERRIDES, *retry_overrides],
        "retry_policy": retry_policy or "LEGACY_CLI_DEFAULTS",
        "authorization": "REQUIRES_EXTERNAL_USER_GRANT_VERIFICATION",
        "credentials_inspected": membership,
        "credential_evidence_scope": "LOCAL_AUTH_MODE_AND_HASHED_ACCOUNT_ONLY" if membership else "NOT_INSPECTED",
        "remote_availability": "NOT_TESTED",
        "model_calls": 0,
        "fallback": "FORBIDDEN",
    }


def codex_wire_correction_evidence(process_evidence: Mapping) -> dict | None:
    contract = process_evidence.get('provider_schema_contract') or {}
    canonical = process_evidence.get('output_schema')
    if (not isinstance(canonical, dict) or process_evidence.get('output_schema_version') != 'schema:chapter-provider-output:canon_extraction:v24'
        or contract.get('version') != CODEX_SCHEMA_PROJECTION_VERSION):
        return None
    def digest(value):
        return 'sha256:'+hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    def reverse(value):
        if isinstance(value, dict):
            branches = value.get('anyOf')
            if (set(value)=={'anyOf'} and isinstance(branches,list) and len(branches)==2
                and branches[1]=={'type':'null'} and branches[0].get('type')=='object'):
                return reverse({**branches[0],'type':['object','null']})
            return {key:reverse(item) for key,item in value.items()}
        if isinstance(value,list):
            return [reverse(item) for item in value]
        return value
    wire = codex_output_schema(canonical)
    if (digest(canonical) != contract.get('canonical_hash') or digest(reverse(wire)) != contract.get('provider_hash')
        or digest(wire)==contract.get('provider_hash')):
        return None
    return {'contract_version':CODEX_NULLABLE_SHARED_TYPES_VERSION,'canonical_hash':digest(canonical),
        'previous_wire_hash':contract['provider_hash'],'corrected_wire_hash':digest(wire),'reversible_equivalence':'EXACT'}
