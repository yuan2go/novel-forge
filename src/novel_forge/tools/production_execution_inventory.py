"""INVARIANT: inventory scanning cannot import or connect to the inspected runtime."""

from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


GENERATOR_VERSION = "1.0.0"
SCHEMA_VERSION = "production-execution-migration-ledger.v1"

SIDE_EFFECT_TYPES = (
    "DETERMINISTIC_LOCAL",
    "DATABASE_AUTHORITY",
    "MODEL_INFERENCE",
    "LOCAL_PROCESS_REMOTE_INFERENCE",
    "AGENT_WORKSPACE_TRANSACTION",
    "REMOTE_EXTERNAL_ACTION",
    "REMOTE_RETRIEVAL",
    "SCRIPTED_FIXTURE",
    "LEGACY_UNKNOWN",
)

REQUIRED_LEDGER_FIELDS = (
    "execution_owner_id",
    "source_file",
    "source_symbol",
    "domain",
    "current_entrypoint",
    "current_adapter",
    "side_effect_type",
    "production_reachable",
    "current_state_store",
    "authority_operation_bound",
    "authority_attempt_bound",
    "external_effect_bound",
    "budget_bound",
    "query_supported",
    "cancel_supported",
    "callback_supported",
    "current_route",
    "target_capability",
    "target_backend",
    "migration_status",
    "legacy_removal_gate",
    "tests",
    "known_risks",
)

_MODEL_METHODS = {
    "analyze",
    "batch",
    "complete",
    "completion",
    "create_completion",
    "embed",
    "embeddings",
    "generate",
    "invoke",
    "review",
    "revise",
}
_RETRIEVAL_METHODS = {
    "crawl",
    "download",
    "embed",
    "fetch",
    "get",
    "pull",
    "rerank",
    "rss",
    "urlopen",
}
_EXTERNAL_ACTION_METHODS = {
    "callback",
    "delete",
    "notify",
    "patch",
    "post",
    "publish",
    "put",
    "send",
    "submit",
    "upload",
    "webhook",
    "withdraw",
}
_PROCESS_NAMES = {
    "asyncio.create_subprocess_exec",
    "asyncio.create_subprocess_shell",
    "os.popen",
    "os.system",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.run",
}
_DATABASE_PREFIXES = (
    "psycopg",
    "psycopg2",
    "asyncpg",
)
_MODEL_PREFIXES = (
    "anthropic",
    "claude",
    "deepseek",
    "openai",
)
_HTTP_PREFIXES = (
    "aiohttp",
    "httpx",
    "requests",
    "urllib.request",
)
_UNCERTAINTY_MARKERS = (
    "external",
    "provider",
    "remote",
    "request",
    "execute",
    "dispatch",
    "launch",
)
_FIXTURE_MARKERS = (
    "/fixtures/",
    "/test/",
    "/tests/",
    "/mock.py",
    "/scripted.py",
    "_fixture.py",
)
_BUSINESS_EXECUTION_ROOTS = (
    "src/novel_forge/modules/",
    "src/novel_forge/api/",
    "src/novel_forge/workflows/",
    "src/novel_forge/workers/",
)
_EXECUTION_IMPLEMENTATION_PATHS = (
    "src/novel_forge/modules/production_execution/",
    "src/novel_forge/modules/provider_control/",
)
_EXECUTION_COMPOSITION_PATHS = frozenset(
    {
        "src/novel_forge/modules/chapter_authority/execution_gateway.py",
    }
)
_FORBIDDEN_BUSINESS_IMPORT_PREFIXES = (
    "subprocess",
    "openai",
    "anthropic",
    "httpx",
    "requests",
    "aiohttp",
    "urllib.request",
    "urllib.error",
)
_FORBIDDEN_BACKEND_IMPORT_PREFIXES = (
    "novel_forge.modules.production_execution.backends",
    "novel_forge.modules.production_execution.process_supervisor",
)
_FORBIDDEN_LEGACY_ADAPTER_SYMBOLS = frozenset(
    {
        "ClaudeCodeAdapter",
        "CodexAdapter",
        "GuardedModelAdapter",
        "LocalCodexCliWorkerMixin",
        "ModelAdapter",
        "ModelAdapterConfig",
        "PROVIDER_ADAPTERS",
        "model_from_env",
    }
)


@dataclass(frozen=True, slots=True)
class _Function:
    module: str
    qualified_name: str
    display_name: str
    path: Path
    node: ast.AST
    source: str
    calls: tuple["_Call", ...]
    fixture: bool


@dataclass(frozen=True, slots=True)
class _Call:
    display: str
    resolved: str
    line: int
    dynamic_method: str = ""
    keyword_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _DirectClassification:
    side_effect_type: str
    current_adapter: str
    indirect: bool = False
    route_hint: str = ""
    status_hint: str = ""


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    content = {key: value for key, value in payload.items() if key != "artifact_hash"}
    encoded = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _source_tree_hash(paths: Iterable[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _module_name(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    if relative.parts[0] == "src":
        parts = list(relative.parts[1:])
    else:
        parts = list(relative.parts)
    parts[-1] = Path(parts[-1]).stem
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _relative_module(current: str, imported: str | None, level: int) -> str:
    if level <= 0:
        return str(imported or "")
    package = current.split(".")[:-1]
    if level > 1:
        package = package[: -(level - 1)]
    if imported:
        package.extend(imported.split("."))
    return ".".join(package)


def _expression_name(node: ast.AST, aliases: Mapping[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        parent = _expression_name(node.value, aliases)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id == "getattr" and len(node.args) >= 2:
            method = node.args[1]
            if isinstance(method, ast.Constant) and isinstance(method.value, str):
                return f"getattr:{method.value}"
    return ""


def _source_display(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError):
        return ""


def _aliases_for_module(module: str, tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            aliases[node.name] = f"{module}.{node.name}"
        elif isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".")[0]] = item.name
        elif isinstance(node, ast.ImportFrom):
            imported_module = _relative_module(module, node.module, node.level)
            for item in node.names:
                if item.name == "*":
                    continue
                value = (
                    f"{imported_module}.{item.name}"
                    if imported_module
                    else item.name
                )
                aliases[item.asname or item.name] = value
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if value is None:
                continue
            resolved = _expression_name(value.func, aliases) if isinstance(value, ast.Call) else _expression_name(value, aliases)
            if not resolved:
                continue
            for target in targets:
                if isinstance(target, ast.Name):
                    aliases[target.id] = resolved
    return aliases


class _LocalCallCollector(ast.NodeVisitor):
    def __init__(self, aliases: Mapping[str, str], root: ast.AST) -> None:
        self.aliases = dict(aliases)
        self.root = root
        self.calls: list[_Call] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.root:
            self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self.root:
            self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node is self.root:
            self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        dynamic = _expression_name(node.value, self.aliases)
        if dynamic.startswith("getattr:"):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.aliases[target.id] = dynamic
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            dynamic = _expression_name(node.value, self.aliases)
            if dynamic.startswith("getattr:") and isinstance(node.target, ast.Name):
                self.aliases[node.target.id] = dynamic
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for item in node.names:
            self.aliases[item.asname or item.name.split(".")[0]] = item.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            for item in node.names:
                if item.name != "*":
                    self.aliases[item.asname or item.name] = (
                        f"{node.module}.{item.name}"
                    )

    def visit_Call(self, node: ast.Call) -> None:
        display = _source_display(node.func)
        resolved = _expression_name(node.func, self.aliases)
        dynamic_method = ""
        if resolved.startswith("getattr:"):
            dynamic_method = resolved.split(":", 1)[1]
            display = resolved
        if display:
            self.calls.append(
                _Call(
                    display=display,
                    resolved=resolved or display,
                    line=int(getattr(node, "lineno", 0) or 0),
                    dynamic_method=dynamic_method,
                    keyword_names=tuple(
                        keyword.arg
                        for keyword in node.keywords
                        if keyword.arg is not None
                    ),
                )
            )
        self.generic_visit(node)


def _functions_in_file(
    root: Path, path: Path, module: str, tree: ast.Module, source: str
) -> list[_Function]:
    aliases = _aliases_for_module(module, tree)
    result: list[_Function] = []
    fixture_path = _is_fixture_path(path.relative_to(root))

    def add(
        node: ast.AST,
        display_name: str,
        qualified_name: str,
        *,
        class_name: str = "",
    ) -> None:
        local_aliases = dict(aliases)
        if class_name:
            local_aliases["self"] = f"{module}.{class_name}"
            local_aliases["cls"] = f"{module}.{class_name}"
        collector = _LocalCallCollector(local_aliases, node)
        collector.visit(node)
        segment = ast.get_source_segment(source, node) or ""
        result.append(
            _Function(
                module=module,
                qualified_name=qualified_name,
                display_name=display_name,
                path=path,
                node=node,
                source=segment,
                calls=tuple(collector.calls),
                fixture=fixture_path
                or "scripted" in display_name.lower()
                or display_name.lower().startswith("mock"),
            )
        )

    module_calls = _LocalCallCollector(aliases, tree)
    module_calls.visit(tree)
    result.append(
        _Function(
            module=module,
            qualified_name=module,
            display_name="<module>",
            path=path,
            node=tree,
            source=source,
            calls=tuple(module_calls.calls),
            fixture=fixture_path,
        )
    )
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add(node, node.name, f"{module}.{node.name}")
        elif isinstance(node, ast.ClassDef):
            class_fixture = fixture_path or "scripted" in node.name.lower() or "mock" in node.name.lower()
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    before = len(result)
                    add(
                        child,
                        f"{node.name}.{child.name}",
                        f"{module}.{node.name}.{child.name}",
                        class_name=node.name,
                    )
                    if class_fixture and len(result) > before:
                        current = result[-1]
                        result[-1] = _Function(
                            module=current.module,
                            qualified_name=current.qualified_name,
                            display_name=current.display_name,
                            path=current.path,
                            node=current.node,
                            source=current.source,
                            calls=current.calls,
                            fixture=True,
                        )
    return result


def _is_fixture_path(path: Path) -> bool:
    value = "/" + str(path).replace("\\", "/").lower()
    return any(marker in value for marker in _FIXTURE_MARKERS)


def _method_name(call: _Call) -> str:
    if call.dynamic_method:
        return call.dynamic_method.lower()
    return (call.resolved or call.display).rsplit(".", 1)[-1].lower()


def _starts_with(value: str, prefixes: Iterable[str]) -> bool:
    lowered = value.lower()
    return any(lowered == prefix or lowered.startswith(prefix + ".") for prefix in prefixes)


def _classify_direct(function: _Function, call: _Call) -> _DirectClassification | None:
    relative = str(function.path).replace("\\", "/").lower()
    resolved = call.resolved
    lowered = resolved.lower()
    method = _method_name(call)
    combined = f"{relative} {function.display_name.lower()} {lowered}"
    governed_execution_projection = (
        resolved.startswith("execution_port.")
        or ".execution_port." in resolved
        or any(
        name == "execution_port" or name.endswith("_execution_port")
        for name in call.keyword_names
        )
    )

    if function.fixture and (
        method in _MODEL_METHODS
        or method in _RETRIEVAL_METHODS
        or method in _EXTERNAL_ACTION_METHODS
        or method in {"execute", "run"}
    ):
        return _DirectClassification("SCRIPTED_FIXTURE", resolved)

    if _starts_with(resolved, _DATABASE_PREFIXES):
        return _DirectClassification("DATABASE_AUTHORITY", resolved)
    if method == "execute" and any(
        marker in lowered
        for marker in (
            "cursor.execute",
            "connection.execute",
            "session.execute",
            "uow.cursor.execute",
        )
    ):
        return _DirectClassification("DATABASE_AUTHORITY", resolved)
    if any(
        marker in combined
        for marker in (
            "command_kernel",
            "authority_",
            "external_effect_runtime",
        )
    ) and method in {
        "admit_command_in_uow",
        "dispatch_external_effect",
        "dispatch_for_update",
        "prepare_effect_dispatch",
        "submit_effect_dispatch_result",
    }:
        return _DirectClassification("DATABASE_AUTHORITY", resolved)

    if resolved in _PROCESS_NAMES or (
        _starts_with(resolved, ("subprocess",)) and method in {"run", "popen", "call", "check_output", "check_call"}
    ):
        if "agent" in combined or "workspace" in combined:
            kind = "AGENT_WORKSPACE_TRANSACTION"
        elif any(marker in combined for marker in ("codex", "claude", "model", "provider", "production_execution")):
            kind = "LOCAL_PROCESS_REMOTE_INFERENCE"
        else:
            kind = "LEGACY_UNKNOWN"
        return _DirectClassification(kind, resolved)

    if "/provider_control/" in relative and method in {
        "cancel",
        "cancel_v2",
        "execute",
        "invoke",
        "query",
        "query_v2",
    }:
        return _DirectClassification("MODEL_INFERENCE", resolved)
    if "/command_kernel/external_effect_runtime.py" in relative and method == "execute":
        return _DirectClassification("REMOTE_EXTERNAL_ACTION", resolved)
    if "/chapter_authority/export_delivery.py" in relative and method == "execute":
        return _DirectClassification("REMOTE_EXTERNAL_ACTION", resolved)
    if (
        "/chapter_authority/handlers.py" in relative
        and method == "invoke"
        and ".provider.invoke" in lowered
    ):
        return _DirectClassification(
            "MODEL_INFERENCE",
            f"PRODUCTION_EXECUTION_PORT:{resolved}",
            route_hint="PRODUCTION_EXECUTION_GATEWAY",
            status_hint="GATEWAY_BOUND",
        )

    model_prefix = _starts_with(resolved, _MODEL_PREFIXES)
    model_chain = any(
        marker in lowered
        for marker in (
            ".chat.completions.create",
            ".completions.create",
            ".messages.create",
            ".responses.create",
        )
    )
    if method in {"embed", "rerank", "embeddings", "embed_batch"}:
        return _DirectClassification(
            "REMOTE_RETRIEVAL",
            (
                f"PRODUCTION_EXECUTION_PORT:{resolved}"
                if governed_execution_projection
                else resolved
            ),
            route_hint=(
                "PRODUCTION_EXECUTION_GATEWAY"
                if governed_execution_projection
                else ""
            ),
            status_hint=(
                "GATEWAY_BOUND" if governed_execution_projection else ""
            ),
        )
    if governed_execution_projection and (
        method in _MODEL_METHODS
        or method == "execute"
        or method
        in {
            "execute_domain_candidate",
            "execute_external_action",
            "execute_longform_analysis",
            "execute_similarity_embedding_pair",
        }
    ):
        side_effect_type = (
            "REMOTE_EXTERNAL_ACTION"
            if method == "execute_external_action"
            else (
                "AGENT_WORKSPACE_TRANSACTION"
                if "agent" in combined or "workspace" in combined
                else (
                    "REMOTE_RETRIEVAL"
                    if "embedding" in method or "rerank" in method
                    else "MODEL_INFERENCE"
                )
            )
        )
        return _DirectClassification(
            side_effect_type,
            f"PRODUCTION_EXECUTION_PORT:{resolved}",
        )
    if (
        resolved.startswith("novel_forge.modules.")
        and not resolved.startswith(
            (
                "novel_forge.modules.production_execution.",
                "novel_forge.modules.provider_control.",
            )
        )
    ):
        # Domain service names such as ``review`` and ``revise`` are not model
        # adapter methods. Their implementations are scanned independently.
        return None
    if model_prefix or model_chain or method in _MODEL_METHODS:
        return _DirectClassification("MODEL_INFERENCE", resolved)

    http_prefix = _starts_with(resolved, _HTTP_PREFIXES)
    if http_prefix and method in {"request", "Request".lower()}:
        return None
    if http_prefix and any(
        marker in combined
        for marker in ("model_adapters", "provider_control", "model inference")
    ) and method in {"get", "post", "send", "urlopen"}:
        return _DirectClassification("MODEL_INFERENCE", resolved)
    if http_prefix and any(
        marker in combined
        for marker in (
            "/publishing/",
            "publishing_feedback_adapters",
            "webhook",
            "notification",
            "mcp_json_rpc",
            "tool_gateway",
        )
    ) and method in {"get", "post", "put", "patch", "delete", "send", "urlopen"}:
        return _DirectClassification("REMOTE_EXTERNAL_ACTION", resolved)
    if http_prefix and method in _RETRIEVAL_METHODS:
        return _DirectClassification("REMOTE_RETRIEVAL", resolved)
    if http_prefix and method in _EXTERNAL_ACTION_METHODS:
        return _DirectClassification("REMOTE_EXTERNAL_ACTION", resolved)
    if method in {"publish", "withdraw", "webhook", "notify"}:
        return _DirectClassification("REMOTE_EXTERNAL_ACTION", resolved)
    if method in {"fetch", "crawl", "rss", "download", "rerank"} and any(
        marker in lowered
        for marker in ("client.", "connector.", "provider.", "adapter.", "remote")
    ):
        return _DirectClassification("REMOTE_RETRIEVAL", resolved)

    if (
        method.startswith(
            (
                "execute_remote",
                "dispatch_remote",
                "launch_remote",
                "run_remote",
                "invoke_remote",
            )
        )
        or (
            method in {"execute", "dispatch", "launch", "request"}
            and any(
                marker in lowered
                for marker in (
                    "adapter.",
                    "client.",
                    "executor.",
                    "provider.",
                    "transport.",
                )
            )
        )
    ):
        return _DirectClassification("LEGACY_UNKNOWN", resolved)
    return None


def _function_classifications(
    functions: list[_Function],
) -> tuple[
    dict[str, _DirectClassification],
    dict[tuple[str, int, str], _DirectClassification],
]:
    summaries: dict[str, _DirectClassification] = {}
    calls: dict[tuple[str, int, str], _DirectClassification] = {}
    known = {function.qualified_name for function in functions}

    for function in functions:
        direct: list[_DirectClassification] = []
        for call in function.calls:
            classification = _classify_direct(function, call)
            if call.resolved in known:
                governed_call = any(
                    name == "execution_port"
                    or name.endswith("_execution_port")
                    for name in call.keyword_names
                )
                legacy_call = any(
                    name in {"model", "adapter", "provider_adapter"}
                    for name in call.keyword_names
                )
                if governed_call and classification is not None:
                    pass
                elif governed_call and _method_name(call) in _MODEL_METHODS:
                    classification = _DirectClassification(
                            "MODEL_INFERENCE",
                            f"PRODUCTION_EXECUTION_PORT:{call.resolved}",
                            route_hint="PRODUCTION_EXECUTION_GATEWAY",
                            status_hint="GATEWAY_BOUND",
                        )
                elif legacy_call and _method_name(call) in _MODEL_METHODS:
                    classification = _DirectClassification(
                        "MODEL_INFERENCE",
                        call.resolved,
                    )
                elif classification is not None:
                    classification = None
            if classification is not None:
                normalized_path = str(function.path).replace("\\", "/").lower()
                guarded = any(
                    marker in function.source.lower()
                    for marker in (
                        "assert_legacy_execution_allowed",
                        "_assert_legacy_execution_allowed",
                        "_require_gateway_for_controlled_environment",
                        "controlled domain execution requires",
                        "legacy execution is blocked",
                        "legacy direct model adapters are disabled",
                    )
                )
                if "/production_execution/" in normalized_path:
                    classification = _DirectClassification(
                        classification.side_effect_type,
                        classification.current_adapter,
                        classification.indirect,
                        "PRODUCTION_EXECUTION_GATEWAY",
                        "GATEWAY_BOUND",
                    )
                elif "/provider_control/" in normalized_path:
                    classification = _DirectClassification(
                        classification.side_effect_type,
                        classification.current_adapter,
                        classification.indirect,
                        "PRODUCTION_EXECUTION_GATEWAY",
                        "GATEWAY_BOUND",
                    )
                elif (
                    "/model_adapters/" in normalized_path
                    and classification.side_effect_type
                    not in {"DETERMINISTIC_LOCAL", "SCRIPTED_FIXTURE"}
                ):
                    classification = _DirectClassification(
                        classification.side_effect_type,
                        classification.current_adapter,
                        classification.indirect,
                        "DIRECT_MODEL_ADAPTER",
                        "LEGACY_BLOCKED",
                    )
                elif (
                    "/chapter_authority/model_effects.py" in normalized_path
                    and "ChapterModelExternalEffectAdapter"
                    in function.display_name
                ):
                    classification = _DirectClassification(
                        classification.side_effect_type,
                        classification.current_adapter,
                        classification.indirect,
                        classification.route_hint,
                        "LEGACY_BLOCKED",
                    )
                elif guarded:
                    classification = _DirectClassification(
                        classification.side_effect_type,
                        classification.current_adapter,
                        classification.indirect,
                        classification.route_hint,
                        "LEGACY_BLOCKED",
                    )
                calls[(function.qualified_name, call.line, call.display)] = classification
                direct.append(classification)
        if function.fixture and function.display_name.rsplit(".", 1)[-1].lower() in (
            _MODEL_METHODS | _RETRIEVAL_METHODS | _EXTERNAL_ACTION_METHODS | {"execute", "run"}
        ):
            direct.append(
                _DirectClassification(
                    "SCRIPTED_FIXTURE", function.qualified_name
                )
            )
        if direct:
            summaries[function.qualified_name] = _strongest(direct)

    changed = True
    while changed:
        changed = False
        for function in functions:
            for call in function.calls:
                target = call.resolved
                if target not in known or target not in summaries:
                    continue
                key = (function.qualified_name, call.line, call.display)
                if key in calls:
                    continue
                source = summaries[target]
                propagated = _DirectClassification(
                    source.side_effect_type,
                    (
                        source.current_adapter
                        if source.current_adapter.startswith(
                            "PRODUCTION_EXECUTION_PORT:"
                        )
                        else target
                    ),
                    indirect=True,
                    route_hint=source.route_hint,
                    status_hint=source.status_hint,
                )
                calls[key] = propagated
                previous = summaries.get(function.qualified_name)
                combined = [propagated] if previous is None else [previous, propagated]
                current = _strongest(combined)
                if current != previous:
                    summaries[function.qualified_name] = current
                    changed = True
    return summaries, calls


def _strongest(
    classifications: Iterable[_DirectClassification],
) -> _DirectClassification:
    priority = {
        "LEGACY_UNKNOWN": 90,
        "AGENT_WORKSPACE_TRANSACTION": 80,
        "REMOTE_EXTERNAL_ACTION": 70,
        "LOCAL_PROCESS_REMOTE_INFERENCE": 60,
        "MODEL_INFERENCE": 50,
        "REMOTE_RETRIEVAL": 40,
        "DATABASE_AUTHORITY": 20,
        "SCRIPTED_FIXTURE": 10,
        "DETERMINISTIC_LOCAL": 0,
    }
    status_priority = {
        "GATEWAY_BOUND": 30,
        "LEGACY_BLOCKED": 20,
        "FIXTURE_PROVEN": 10,
        "": 0,
    }
    return max(
        classifications,
        key=lambda item: (
            priority[item.side_effect_type],
            status_priority.get(item.status_hint, 0),
            int(item.route_hint == "PRODUCTION_EXECUTION_GATEWAY"),
        ),
    )


def _domain(relative: str) -> str:
    parts = Path(relative).parts
    try:
        index = parts.index("modules")
        return parts[index + 1] if index + 1 < len(parts) else "modules"
    except ValueError:
        if "model_adapters" in parts:
            return "model_adapters"
        if "infrastructure" in parts:
            return "infrastructure"
        if "storage" in parts:
            return "storage"
        if parts and parts[0] == "scripts":
            return "scripts"
        return parts[-2] if len(parts) > 1 else "repository"


def _target_capability(
    relative: str,
    function: _Function,
    call: _Call,
    side_effect_type: str,
) -> str:
    text = " ".join(
        (
            relative.lower(),
            function.display_name.lower(),
            call.display.lower(),
            call.resolved.lower(),
        )
    )
    if side_effect_type in {
        "DATABASE_AUTHORITY",
        "DETERMINISTIC_LOCAL",
        "LEGACY_UNKNOWN",
    }:
        return ""
    if "embed" in text or "embedding" in text:
        return "retrieval.embed"
    if "rerank" in text:
        return "retrieval.rerank"
    if "topic" in text:
        return "creative.topic.generate"
    if "creative" in text or "proposal" in text:
        return "creative.proposal.generate"
    if "theme" in text:
        return "theme.question.generate"
    if "ending" in text:
        return "ending.intent.generate"
    if "world" in text:
        return "world.design.generate"
    if "character" in text:
        return "character.cast.generate"
    if "chapter_group" in text or "chapter-group" in text:
        return "planning.chapter_group.generate"
    if "chapter_plan" in text or "chapter-plan" in text:
        return "planning.chapter.generate"
    if "volume" in text:
        return "planning.volume.generate"
    if "arc_plan" in text or "arc-plan" in text:
        return "planning.arc.generate"
    if "outline" in text or "book_plan" in text or "book-plan" in text:
        return "planning.book.generate"
    if "draft" in text or "prose" in text:
        return "prose.chapter.draft"
    if "revision" in text or "revise" in text or "/editor/" in text:
        return "revision.chapter.revise"
    if "canon" in text:
        return "canon.extract"
    if "originality" in text:
        return "quality.originality.judge"
    if "reader_outcome" in text or "reader outcome" in text:
        return "quality.reader_outcome.judge"
    if "pairwise" in text:
        return "quality.pairwise.judge"
    if "platform" in text and "quality" in text:
        return "quality.platform.judge"
    if "quality" in text or "judge" in text:
        return "quality.intrinsic.judge"
    if "review" in text:
        return "review.chapter.evaluate"
    if "rule" in text and ("mkaos" in text or "extract" in text):
        return "mkaos.rule.extract"
    if "template" in text and ("mkaos" in text or "extract" in text):
        return "mkaos.template.extract"
    if any(marker in text for marker in ("mkaos", "decomposition", "/analysis/")):
        return "mkaos.knowledge.extract"
    if "plan_vs_actual" in text or "plan-vs-actual" in text:
        return "longform.plan_vs_actual.judge"
    if "arc_closure" in text or "arc-closure" in text:
        return "longform.arc_closure.judge"
    if "plan_change" in text or "plan-change" in text:
        return "longform.plan_change.generate"
    if "longform" in text or "recap" in text:
        return "longform.recap.analyze"
    if "agent" in text or "workspace" in text:
        return "agent.workspace.execute"
    if "fetch_platform_feedback" in text or "feedback_fetch" in text:
        return "feedback.platform.fetch"
    if "publishing" in text or "publish" in text:
        if any(marker in text for marker in ("withdraw", "retract")):
            return "publishing.release.withdraw"
        if any(marker in text for marker in ("query", "status")):
            return "publishing.release.query"
        return "publishing.release.submit"
    if "feedback" in text:
        return "feedback.platform.fetch"
    if any(marker in text for marker in ("source", "fetch", "crawl", "rss")):
        return "source.remote.fetch"
    if any(marker in text for marker in ("notification", "notify", "webhook")):
        return "notification.send"
    if "export_delivery" in text or "object_store" in text or "blob.upload" in text:
        return "storage.object.put"
    if side_effect_type == "AGENT_WORKSPACE_TRANSACTION":
        return "agent.workspace.execute"
    if side_effect_type == "REMOTE_RETRIEVAL":
        return "source.remote.fetch"
    if side_effect_type == "REMOTE_EXTERNAL_ACTION" and "publish" in text:
        return "publishing.release.submit"
    return ""


def _target_backend(side_effect_type: str) -> str:
    return {
        "MODEL_INFERENCE": "remote-provider",
        "LOCAL_PROCESS_REMOTE_INFERENCE": "codex-cli",
        "AGENT_WORKSPACE_TRANSACTION": "agent-workspace",
        "REMOTE_EXTERNAL_ACTION": "remote-external-action",
        "REMOTE_RETRIEVAL": "remote-external-action",
        "SCRIPTED_FIXTURE": "scripted-fixture",
    }.get(side_effect_type, "")


def _state_store(function: _Function, classification: _DirectClassification) -> str:
    text = f"{function.source} {classification.current_adapter}".lower()
    if classification.side_effect_type == "DATABASE_AUTHORITY" or (
        "authority_" in text and ("psycopg" in text or "database_url" in text)
    ):
        return "POSTGRESQL_AUTHORITY"
    if "inmemoryexecutionrecordstore" in text:
        return "WORKER_LOCAL_EXECUTION_RECORD"
    if "persistentexecutiondirectory" in text or "processreceipt" in text:
        return "PERSISTENT_EXECUTION_DIRECTORY"
    if "localstorage" in text:
        return "LEGACY_LOCAL_STORAGE"
    if classification.side_effect_type == "SCRIPTED_FIXTURE":
        return "FIXTURE_MEMORY"
    return "UNKNOWN"


def _current_route(
    function: _Function, classification: _DirectClassification
) -> str:
    if classification.route_hint:
        return classification.route_hint
    text = f"{function.source} {classification.current_adapter}".lower()
    if classification.side_effect_type == "DATABASE_AUTHORITY":
        return "POSTGRESQL_AUTHORITY"
    if classification.side_effect_type == "SCRIPTED_FIXTURE":
        return "SCRIPTED_FIXTURE"
    if (
        classification.current_adapter.startswith("PRODUCTION_EXECUTION_PORT:")
        or "productionexecutiongateway" in text
        or "/production_execution/" in str(function.path).replace("\\", "/")
    ):
        return "PRODUCTION_EXECUTION_GATEWAY"
    if "call_model_via_router" in text or "model_router" in text:
        return "MODEL_ROUTER"
    if classification.side_effect_type in {
        "LOCAL_PROCESS_REMOTE_INFERENCE",
        "AGENT_WORKSPACE_TRANSACTION",
    }:
        return "DIRECT_PROCESS"
    if classification.side_effect_type == "MODEL_INFERENCE":
        return "DIRECT_MODEL_ADAPTER"
    if classification.side_effect_type in {
        "REMOTE_EXTERNAL_ACTION",
        "REMOTE_RETRIEVAL",
    }:
        return "DIRECT_EXTERNAL_CLIENT"
    return "LEGACY_UNKNOWN"


def _production_reachable(relative: str, function: _Function) -> bool:
    normalized = "/" + relative.replace("\\", "/").lower()
    if (
        function.fixture
        or normalized.startswith("/scripts/")
        or normalized.startswith("/src/novel_forge/tools/")
    ):
        return False
    return normalized.startswith("/src/")


def _tests_for(relative: str, tests: Mapping[str, str]) -> list[str]:
    stem = Path(relative).stem
    module_parts = Path(relative).with_suffix("").parts
    symbol = ".".join(module_parts[-3:])
    matches = [
        path
        for path, source in tests.items()
        if stem in source or symbol in source or stem in Path(path).stem
    ]
    return sorted(matches)[:12]


def _entry(
    *,
    root: Path,
    relative: str,
    function: _Function,
    call: _Call,
    classification: _DirectClassification,
    tests: Mapping[str, str],
    ordinal: int,
) -> dict[str, Any]:
    production = _production_reachable(relative, function)
    source = function.source.lower()
    governed_projection = (
        classification.current_adapter.startswith(
            "PRODUCTION_EXECUTION_PORT:"
        )
        or (
            classification.route_hint == "PRODUCTION_EXECUTION_GATEWAY"
            and classification.status_hint == "GATEWAY_BOUND"
        )
    )
    operation_bound = governed_projection or "operation_id" in source and (
        "authority" in source or "external_effect" in source or "executionrequest" in source
    )
    attempt_bound = governed_projection or (
        "attempt_id" in source and "fencing_token" in source
    )
    effect_bound = (
        governed_projection
        or "external_effect" in source
        or "plan_external_effect" in source
    )
    budget_bound = (
        governed_projection
        or "budget_reservation" in source
        or "budget_policy" in source
    )
    route = _current_route(function, classification)
    capability = _target_capability(
        relative, function, call, classification.side_effect_type
    )
    if not capability and classification.side_effect_type in {
        "MODEL_INFERENCE",
        "LOCAL_PROCESS_REMOTE_INFERENCE",
        "AGENT_WORKSPACE_TRANSACTION",
    }:
        if any(
            marker in relative
            for marker in (
                "/model_adapters/",
                "/production_execution/",
                "/provider_control/",
            )
        ):
            capability = "capability-registry:execution-request"
        elif any(
            marker in relative
            for marker in (
                "/workflow",
                "/loop_kernel/",
                "/tool_gateway/",
            )
        ):
            capability = "capability-registry:operation-dispatch"
        elif any(
            marker in f"{relative} {function.display_name} {call.display}".lower()
            for marker in ("analysis", "analyze", "decompose")
        ):
            capability = "mkaos.knowledge.extract"
        else:
            capability = "capability-registry:operation-dispatch"
    if not capability and classification.side_effect_type == "REMOTE_EXTERNAL_ACTION":
        if "external_effect" in relative:
            capability = "capability-registry:external-effect"
        elif "tool_gateway" in relative:
            capability = "tool.remote.invoke"
        elif "chapter_authority" in relative:
            capability = "storage.object.put"
        else:
            capability = "capability-registry:external-effect"
    guarded_legacy = any(
        marker in source
        for marker in (
            "assert_legacy_execution_allowed",
            "_assert_legacy_execution_allowed",
            "_require_gateway_for_controlled_environment",
            "controlled domain execution requires",
            "legacy execution is blocked",
            "legacy direct model adapters are disabled",
        )
    )
    if classification.status_hint:
        status = classification.status_hint
    elif classification.side_effect_type == "SCRIPTED_FIXTURE":
        status = "FIXTURE_PROVEN"
    elif classification.side_effect_type in {
        "DATABASE_AUTHORITY",
        "DETERMINISTIC_LOCAL",
    }:
        status = "CLASSIFIED"
    elif route == "PRODUCTION_EXECUTION_GATEWAY" and operation_bound and attempt_bound:
        status = "GATEWAY_BOUND"
    elif production and guarded_legacy:
        status = "LEGACY_BLOCKED"
    else:
        status = "DISCOVERED"
    identity = "|".join(
        (
            relative,
            function.qualified_name,
            call.display,
            str(ordinal),
        )
    )
    owner_id = "execution-owner:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    risks: list[str] = []
    if classification.indirect:
        risks.append("indirect wrapper")
    if production and classification.side_effect_type == "LEGACY_UNKNOWN":
        risks.append("production-reachable LEGACY_UNKNOWN blocks migration completion")
    if status == "LEGACY_BLOCKED":
        risks.append(
            "development/test compatibility retained; controlled execution fails closed"
        )
    elif production and route != "PRODUCTION_EXECUTION_GATEWAY" and classification.side_effect_type not in {
        "DATABASE_AUTHORITY",
        "DETERMINISTIC_LOCAL",
        "SCRIPTED_FIXTURE",
    }:
        risks.append("production execution bypasses the governed gateway")
    if status != "LEGACY_BLOCKED" and production and not attempt_bound and classification.side_effect_type not in {
        "DATABASE_AUTHORITY",
        "DETERMINISTIC_LOCAL",
    }:
        risks.append("no Authority Attempt and fence binding detected")
    if status != "LEGACY_BLOCKED" and production and classification.side_effect_type in {
        "MODEL_INFERENCE",
        "LOCAL_PROCESS_REMOTE_INFERENCE",
        "AGENT_WORKSPACE_TRANSACTION",
        "REMOTE_EXTERNAL_ACTION",
        "REMOTE_RETRIEVAL",
    } and not effect_bound:
        risks.append("no ExternalEffect binding detected")
    method = _method_name(call)
    return {
        "execution_owner_id": owner_id,
        "source_file": relative,
        "source_symbol": function.display_name,
        "domain": _domain(relative),
        "current_entrypoint": call.display,
        "current_adapter": classification.current_adapter,
        "side_effect_type": classification.side_effect_type,
        "production_reachable": production,
        "current_state_store": _state_store(function, classification),
        "authority_operation_bound": operation_bound,
        "authority_attempt_bound": attempt_bound,
        "external_effect_bound": effect_bound,
        "budget_bound": budget_bound,
        "query_supported": "supports_query" in source or method in {"query", "reconcile"},
        "cancel_supported": "supports_cancel" in source or method in {"cancel", "withdraw"},
        "callback_supported": "supports_callback" in source or method == "callback",
        "current_route": route,
        "target_capability": capability,
        "target_backend": _target_backend(classification.side_effect_type),
        "migration_status": status,
        "legacy_removal_gate": (
            "real-provider validation recorded; zero controlled configuration references; compatibility caller count is zero"
            if status == "LEGACY_BLOCKED"
            else "all callers gateway-bound; fixture and PostgreSQL recovery proven; architecture guard active"
            if production
            else "non-production path remains isolated and cannot produce production proof"
        ),
        "tests": _tests_for(relative, tests),
        "known_risks": risks,
    }


def scan_repository_execution_boundaries(
    repo_root: str | Path,
) -> list[dict[str, Any]]:

    root = Path(repo_root).resolve()
    violations: list[dict[str, Any]] = []
    paths = sorted((root / "src/novel_forge").rglob("*.py"))
    for path in paths:
        relative = str(path.relative_to(root)).replace("\\", "/")
        if not relative.startswith(_BUSINESS_EXECUTION_ROOTS):
            continue
        if relative.startswith(_EXECUTION_IMPLEMENTATION_PATHS):
            continue
        if relative in _EXECUTION_COMPOSITION_PATHS:
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative)
        except (OSError, SyntaxError) as exc:
            violations.append(
                {
                    "code": "AST_PARSE_ERROR",
                    "source_file": relative,
                    "source_symbol": "<module>",
                    "line": int(getattr(exc, "lineno", 0) or 0),
                    "detail": str(exc),
                }
            )
            continue
        module = _module_name(root, path)
        for node in ast.walk(tree):
            imported: list[tuple[str, str]] = []
            if isinstance(node, ast.Import):
                imported = [(item.name, "") for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [
                    (node.module, item.name)
                    for item in node.names
                    if item.name != "*"
                ]
            for imported_module, imported_name in imported:
                if _starts_with(
                    imported_module, _FORBIDDEN_BUSINESS_IMPORT_PREFIXES
                ):
                    violations.append(
                        _boundary_violation(
                            "DIRECT_RUNTIME_IMPORT",
                            relative,
                            node,
                            f"{imported_module}.{imported_name}".rstrip("."),
                        )
                    )
                if _starts_with(
                    imported_module, _FORBIDDEN_BACKEND_IMPORT_PREFIXES
                ):
                    violations.append(
                        _boundary_violation(
                            "CONCRETE_BACKEND_IMPORT",
                            relative,
                            node,
                            f"{imported_module}.{imported_name}".rstrip("."),
                        )
                    )
                if (
                    _starts_with(
                        imported_module, ("novel_forge.model_adapters",)
                    )
                    and imported_name in _FORBIDDEN_LEGACY_ADAPTER_SYMBOLS
                ):
                    violations.append(
                        _boundary_violation(
                            "LEGACY_ADAPTER_IMPORT",
                            relative,
                            node,
                            f"{imported_module}.{imported_name}",
                        )
                    )
        for function in _functions_in_file(root, path, module, tree, source):
            for call in function.calls:
                resolved = call.resolved
                method = _method_name(call)
                if resolved in _PROCESS_NAMES or (
                    _starts_with(resolved, _HTTP_PREFIXES)
                    and method in {"get", "post", "put", "delete", "send", "urlopen"}
                ):
                    violations.append(
                        {
                            "code": "DIRECT_RUNTIME_CALL",
                            "source_file": relative,
                            "source_symbol": function.display_name,
                            "line": call.line,
                            "detail": resolved,
                        }
                    )
                if resolved.endswith(
                    (".call_model_via_router", ".model_from_env")
                ):
                    violations.append(
                        {
                            "code": "LEGACY_EXECUTION_CALL",
                            "source_file": relative,
                            "source_symbol": function.display_name,
                            "line": call.line,
                            "detail": resolved,
                        }
                    )
                parts = resolved.lower().split(".")
                receiver = parts[-2] if len(parts) >= 2 else ""
                if (
                    receiver in {"adapter", "model", "client"}
                    and method in {"generate", "review", "revise", "analyze", "embed", "rerank"}
                    and relative
                    != "src/novel_forge/modules/chapter_authority/model_effects.py"
                ):
                    violations.append(
                        {
                            "code": "DIRECT_ADAPTER_CALL",
                            "source_file": relative,
                            "source_symbol": function.display_name,
                            "line": call.line,
                            "detail": resolved,
                        }
                    )
    return sorted(
        violations,
        key=lambda item: (
            item["source_file"],
            item["line"],
            item["code"],
            item["detail"],
        ),
    )


def _boundary_violation(
    code: str,
    relative: str,
    node: ast.AST,
    detail: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "source_file": relative,
        "source_symbol": "<module>",
        "line": int(getattr(node, "lineno", 0) or 0),
        "detail": detail,
    }


def build_execution_inventory(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    paths = sorted(
        path
        for directory in (root / "src", root / "scripts")
        if directory.exists()
        for path in directory.rglob("*.py")
        if "__pycache__" not in path.parts
    )
    tests = {
        str(path.relative_to(root)): path.read_text(encoding="utf-8")
        for path in sorted((root / "tests").rglob("test_*.py"))
    } if (root / "tests").exists() else {}
    functions: list[_Function] = []
    parse_errors: list[dict[str, Any]] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            parse_errors.append(
                {
                    "source_file": str(path.relative_to(root)),
                    "line": int(exc.lineno or 0),
                    "message": str(exc),
                }
            )
            continue
        module = _module_name(root, path)
        functions.extend(_functions_in_file(root, path, module, tree, source))

    _summaries, classifications = _function_classifications(functions)
    entries: list[dict[str, Any]] = []
    ordinal_by_identity: defaultdict[tuple[str, str, str], int] = defaultdict(int)
    for function in functions:
        relative = str(function.path.relative_to(root))
        for call in function.calls:
            classification = classifications.get(
                (function.qualified_name, call.line, call.display)
            )
            if classification is None:
                continue
            key = (relative, function.qualified_name, call.display)
            ordinal_by_identity[key] += 1
            entries.append(
                _entry(
                    root=root,
                    relative=relative,
                    function=function,
                    call=call,
                    classification=classification,
                    tests=tests,
                    ordinal=ordinal_by_identity[key],
                )
            )
        method = function.display_name.rsplit(".", 1)[-1].lower()
        if function.fixture and method in (
            _MODEL_METHODS
            | _RETRIEVAL_METHODS
            | _EXTERNAL_ACTION_METHODS
            | {"execute", "run"}
        ):
            display = function.display_name
            if any(
                entry["source_file"] == relative
                and entry["source_symbol"] == function.display_name
                and entry["current_entrypoint"] == display
                for entry in entries
            ):
                continue
            synthetic = _Call(
                display=display,
                resolved=function.qualified_name,
                line=int(getattr(function.node, "lineno", 0) or 0),
            )
            classification = _DirectClassification(
                "SCRIPTED_FIXTURE", function.qualified_name
            )
            key = (relative, function.qualified_name, display)
            ordinal_by_identity[key] += 1
            entries.append(
                _entry(
                    root=root,
                    relative=relative,
                    function=function,
                    call=synthetic,
                    classification=classification,
                    tests=tests,
                    ordinal=ordinal_by_identity[key],
                )
            )
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for entry in entries:
        key = (
            entry["source_file"],
            entry["source_symbol"],
            entry["current_entrypoint"],
            entry["side_effect_type"],
        )
        unique.setdefault(key, entry)
    entries = sorted(
        unique.values(),
        key=lambda item: (
            item["source_file"],
            item["source_symbol"],
            item["current_entrypoint"],
            item["execution_owner_id"],
        ),
    )
    blocking = [
        item["execution_owner_id"]
        for item in entries
        if item["production_reachable"]
        and (
            item["side_effect_type"] == "LEGACY_UNKNOWN"
            or item["migration_status"] == "DISCOVERED"
        )
    ]
    counts = Counter(item["side_effect_type"] for item in entries)
    migration_counts = Counter(item["migration_status"] for item in entries)
    boundary_violations = scan_repository_execution_boundaries(root)
    repository_migration_complete = not any(
        (blocking, boundary_violations, parse_errors)
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "source_tree_hash": _source_tree_hash(paths, root),
        "scanned_file_count": len(paths),
        "entry_count": len(entries),
        "summary": {kind: counts.get(kind, 0) for kind in SIDE_EFFECT_TYPES},
        "migration_summary": dict(sorted(migration_counts.items())),
        "blocking_owner_ids": blocking,
        "architecture_boundary_violations": boundary_violations,
        "parse_errors": parse_errors,
        "evidence_flags": {
            "repository_inventory_generated": True,
            "production_execution_repository_inventory_complete": (
                repository_migration_complete
            ),
            "legacy_production_execution_blocked": (
                repository_migration_complete
                and any(
                    item["production_reachable"]
                    and item["migration_status"] == "LEGACY_BLOCKED"
                    for item in entries
                )
            ),
            "repository_execution_migration_implemented": (
                repository_migration_complete
            ),
            "real_provider_proven": False,
            "production_verified": False,
        },
        "entries": entries,
    }
    payload["artifact_hash"] = _canonical_hash(payload)
    return payload


def _markdown(manifest: Mapping[str, Any]) -> str:
    rows = [
        "# Production Execution Migration Ledger",
        "",
        "AST-derived inventory of uncertain execution, external effects, database Authority boundaries, and scripted fixtures. Code and tests are the evidence source; this report does not upgrade real-provider or production proof.",
        "",
        "## Summary",
        "",
        f"- Source tree: `{manifest['source_tree_hash']}`",
        f"- Scanned Python files: {manifest['scanned_file_count']}",
        f"- Execution entries: {manifest['entry_count']}",
        f"- Production migration blockers (`LEGACY_UNKNOWN` or `DISCOVERED`): {len(manifest['blocking_owner_ids'])}",
        "- Architecture boundary violations: "
        f"{len(manifest.get('architecture_boundary_violations', []))}",
        "- `real_provider_proven=false`",
        "- `production_verified=false`",
        "",
        "| Classification | Count |",
        "|---|---:|",
    ]
    rows.extend(
        f"| `{kind}` | {manifest['summary'][kind]} |" for kind in SIDE_EFFECT_TYPES
    )
    rows.extend(
        [
            "",
            "## Blocking Entries",
            "",
        ]
    )
    blockers = set(manifest["blocking_owner_ids"])
    blocked_entries = [
        item for item in manifest["entries"] if item["execution_owner_id"] in blockers
    ]
    if blocked_entries:
        rows.extend(
            [
                "| Owner | Source | Symbol | Entrypoint | Risk |",
                "|---|---|---|---|---|",
            ]
        )
        rows.extend(
            "| `{execution_owner_id}` | `{source_file}` | `{source_symbol}` | `{current_entrypoint}` | {risk} |".format(
                **entry,
                risk="; ".join(entry["known_risks"]),
            )
            for entry in blocked_entries
        )
    else:
        rows.append("No production-reachable `LEGACY_UNKNOWN` entry was detected.")
    rows.extend(
        [
            "",
            "## Execution Migration Matrix",
            "",
            "| Owner | Domain | Source | Type | Route | Capability | Backend | Authority/Attempt/Effect | Status |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )
    rows.extend(
        "| `{execution_owner_id}` | `{domain}` | `{source_file}` | `{side_effect_type}` | `{current_route}` | `{target_capability}` | `{target_backend}` | {authority_operation_bound}/{authority_attempt_bound}/{external_effect_bound} | `{migration_status}` |".format(
            **entry
        )
        for entry in manifest["entries"]
    )
    rows.extend(
        [
            "",
            "## Machine-readable Evidence",
            "",
            "The complete record, including state-store, budget, query/cancel/callback, tests, removal gates, and risks, is stored in `production-execution-migration-ledger.json`.",
            "",
        ]
    )
    return "\n".join(rows)


def write_execution_inventory(
    repo_root: str | Path,
    json_output: str | Path,
    markdown_output: str | Path,
) -> dict[str, Any]:
    manifest = build_execution_inventory(repo_root)
    json_path = Path(json_output)
    markdown_path = Path(markdown_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown(manifest), encoding="utf-8")
    return manifest


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate the Production Execution migration ledger."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--json-output",
        default="build/reports/production-execution-inventory.json",
    )
    parser.add_argument(
        "--markdown-output",
        default="build/reports/production-execution-inventory.md",
    )
    arguments = parser.parse_args()
    write_execution_inventory(
        arguments.repo_root,
        arguments.json_output,
        arguments.markdown_output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
