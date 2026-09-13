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


CODEX_SCHEMA_PROJECTION_VERSION = "codex-structured-schema.v2"


def codex_local_binding_hash(*, codex_home: str, executable: str, entitlement: Mapping[str, str] | None) -> str:
    return hashlib.sha256(json.dumps({
        "codex_home": codex_home,
        "executable": executable,
        "entitlement": dict(entitlement) if entitlement is not None else None,
        "input_only_overrides": CODEX_INPUT_ONLY_OVERRIDES,
        "schema_projection": CODEX_SCHEMA_PROJECTION_VERSION,
    }, sort_keys=True).encode()).hexdigest()


def codex_output_schema(schema: dict) -> dict:
    result = {k: v for k, v in schema.items() if k != "uniqueItems"}
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
    missing = [name for name in required if not str(values.get(name) or "").strip()]
    return {
        "state": "BLOCKED" if blockers else "LOCAL_PROCESS_VERIFIED",
        "identity": identity,
        "blockers": blockers,
        "missing_configuration": missing,
        "invocation_overrides": list(CODEX_INPUT_ONLY_OVERRIDES),
        "authorization": "REQUIRES_EXTERNAL_USER_GRANT_VERIFICATION",
        "credentials_inspected": False,
        "remote_availability": "NOT_TESTED",
        "model_calls": 0,
        "fallback": "FORBIDDEN",
    }
