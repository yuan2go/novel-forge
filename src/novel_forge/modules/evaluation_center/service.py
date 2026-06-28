from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.model_adapters import GuardedModelAdapter, ModelAdapter, model_from_env, validate_model_output
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.schemas import (
    ModelBenchmarkRun,
    ModelBenchmarkTask,
    ModelComparisonReport,
    ModelProfile,
    ModelRoutingPolicy,
    PromptRegressionReport,
    PromptVersion,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage

EVALUATION_TYPES = {
    "model_profile",
    "model_benchmark_task",
    "model_benchmark_run",
    "model_comparison_report",
    "model_routing_policy",
    "prompt_version",
    "prompt_regression_report",
}


def create_model_profile(
    storage: LocalStorage,
    *,
    provider: str,
    model_name: str,
    task_types: list[str] | None = None,
    status: str = "candidate",
    capabilities: dict[str, Any] | None = None,
    cost_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with AgentExecutionContext(
        storage,
        agent_key="model_evaluation",
        operation="create-model-profile",
        output_types=["model_profile"],
        sla_seconds=300,
    ) as run:
        run.guard("write_model_profile", "model_profile")
        asset = ModelProfile(
            title=f"{provider}/{model_name}",
            tags=["model", provider, status, *[str(item) for item in task_types or []]],
            content={
                "profile_id": make_id("model_profile", f"{provider}-{model_name}"),
                "provider": provider,
                "model_name": model_name,
                "task_types": task_types or [],
                "capabilities": capabilities or _default_capabilities(task_types or []),
                "cost_profile": cost_profile or {"input_per_1k": 0, "output_per_1k": 0, "currency": "USD", "source": "manual"},
                "status": status,
                "created_at": utc_now(),
            },
            metadata={"provider": provider, "model_name": model_name},
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]])
        return result


def create_model_benchmark_task(
    storage: LocalStorage,
    *,
    task_type: str,
    input_assets: list[str | Path],
    rubric: dict[str, Any] | None = None,
    expected_output_type: str = "generate",
    prompt_template: str = "",
    workspace_path: str | None = None,
) -> dict[str, Any]:
    refs = [_asset_ref(storage, item) for item in input_assets]
    project = _project_scope(storage, refs, workspace_path=workspace_path)
    with AgentExecutionContext(
        storage,
        agent_key="model_evaluation",
        operation="create-model-benchmark-task",
        input_assets=input_assets,
        output_types=["model_benchmark_task"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
        run.guard("write_model_benchmark_task", "model_benchmark_task")
        task_id = make_id("benchmark_task", task_type)
        asset = ModelBenchmarkTask(
            title=f"{task_type} benchmark task",
            tags=["model-benchmark", task_type],
            content={
                "task_id": task_id,
                "task_type": task_type,
                "input_assets": refs,
                "rubric": rubric or _default_rubric(task_type),
                "expected_output_type": expected_output_type,
                "prompt_template": prompt_template or _default_prompt_template(task_type),
                "created_at": utc_now(),
            },
            metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", "")},
            references=filter_project_safe_references(storage, str(project.get("project_id", "")), [ref["id"] for ref in refs] + [ref["path"] for ref in refs]),
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]])
        return result


def create_benchmark_task_from_generation_run(
    storage: LocalStorage,
    generation_run_path: str | Path,
    *,
    task_type: str = "generation",
    expected_output_type: str = "generate",
    prompt_template: str = "",
) -> dict[str, Any]:
    path = resolve_path(storage.root, generation_run_path)
    generation = storage.read_asset(path)
    if generation.type != "generation_run":
        raise ValueError("generation_run_path must point to a generation_run asset")
    content = generation.content if isinstance(generation.content, dict) else {}
    input_assets = _dedupe(
        [
            str(content.get("input_asset_path", "")),
            str(content.get("context_bundle_path", "")),
            str(content.get("output_asset_path", "")),
        ]
    )
    rubric = {
        "task_type": task_type,
        "source_generation_run_id": generation.id,
        "dimensions": ["schema_validity", "context_adherence", "quality_signal", "latency", "cost"],
        "weights": {"schema_validity": 0.3, "context_adherence": 0.25, "quality_signal": 0.25, "latency": 0.1, "cost": 0.1},
        "target_chars": 1200,
    }
    project = project_scope_from_asset(storage, generation, input_path=path)
    result = create_model_benchmark_task(
        storage,
        task_type=task_type,
        input_assets=input_assets,
        rubric=rubric,
        expected_output_type=expected_output_type,
        prompt_template=prompt_template
        or "Replay this production generation run as a benchmark. Respect the recorded context bundle and output schema.",
        workspace_path=str(project.get("workspace_path", "")),
    )
    task_asset = result.get("asset", {}) if isinstance(result.get("asset", {}), dict) else {}
    task_content = task_asset.get("content", {}) if isinstance(task_asset.get("content", {}), dict) else {}
    task_metadata = task_asset.get("metadata", {}) if isinstance(task_asset.get("metadata", {}), dict) else {}
    task_content["source_generation_run_id"] = generation.id
    task_content["source_generation_run_path"] = _display_path(storage.root, path)
    task_content["production_trace"] = {
        "provider": content.get("provider", ""),
        "model": content.get("model", ""),
        "prompt_version": content.get("prompt_version", ""),
        "context_bundle_path": content.get("context_bundle_path", ""),
        "output_asset_path": content.get("output_asset_path", ""),
    }
    task_metadata["source_generation_run_path"] = _display_path(storage.root, path)
    task_asset["content"] = task_content
    task_asset["metadata"] = task_metadata
    task_path = resolve_path(storage.root, result["path"])
    storage.write_json(task_path, task_asset)
    return {"path": result["path"], "asset": task_asset, "validation": result.get("validation", {"ok": True, "errors": []})}


def run_model_benchmark(
    storage: LocalStorage,
    task_path: str | Path,
    *,
    provider: str = "mock",
    model_name: str = "mock-model",
    model: ModelAdapter | None = None,
) -> dict[str, Any]:
    path = resolve_path(storage.root, task_path)
    task = storage.read_asset(path)
    if task.type != "model_benchmark_task":
        raise ValueError("task_path must point to a model_benchmark_task asset")
    project = project_scope_from_asset(storage, task, input_path=path)
    with AgentExecutionContext(
        storage,
        agent_key="model_evaluation",
        operation="run-model-benchmark",
        input_assets=[path],
        output_types=["model_benchmark_run"],
        workspace_path=str(project.get("workspace_path", "")),
        model_provider=provider,
        model_name=model_name,
        sla_seconds=900,
    ) as run:
        run.guard("read_asset")
        task_type = str(task.content.get("task_type", "generate"))
        adapter = GuardedModelAdapter(model or _model_for_benchmark(task_type, provider=provider, model_name=model_name), storage, run.path)
        started = time.perf_counter()
        status = "succeeded"
        error = ""
        raw_output: dict[str, Any] = {}
        try:
            raw_output = _run_adapter(adapter, task)
            validated = _validate_expected(task.content.get("expected_output_type", "generate"), raw_output)
        except Exception as exc:
            status = "failed"
            error = str(exc)
            validated = {}
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        scores = _score_output(task, validated, status=status, latency_ms=latency_ms)
        cost_estimate = _estimate_run_cost(storage, provider=provider, model_name=model_name, scores=scores, task=task)
        run.guard("write_model_benchmark_run", "model_benchmark_run")
        asset = ModelBenchmarkRun(
            title=f"{provider}/{model_name} on {task.title or task.id}",
            source=task.id,
            tags=["model-benchmark-run", str(task.content.get("task_type", "")), status, provider],
            content={
                "run_id": make_id("benchmark_run", f"{task.id}-{provider}-{model_name}"),
                "task_id": task.content.get("task_id", task.id),
                "task_path": _display_path(storage.root, path),
                "task_type": task.content.get("task_type", ""),
                "provider": provider,
                "model_name": model_name,
                "scores": scores,
                "latency_ms": latency_ms,
                "cost_estimate": cost_estimate,
                "status": status,
                "error": error,
                "raw_output": raw_output,
                "validated_output": validated,
                "created_at": utc_now(),
            },
            metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", ""), "provider": provider, "model_name": model_name},
            references=filter_project_safe_references(storage, str(project.get("project_id", "")), [task.id, _display_path(storage.root, path)]),
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]], token_used=int(scores.get("output_chars", 0)))
        return result


def compare_model_runs(
    storage: LocalStorage,
    run_paths: list[str | Path],
    *,
    task_type: str = "",
    workspace_path: str | None = None,
) -> dict[str, Any]:
    runs = [_read_run(storage, item) for item in run_paths]
    project = _project_scope(storage, [{"path": run["path"], "id": run["id"], "type": run["asset"].get("type", "")} for run in runs], workspace_path=workspace_path)
    with AgentExecutionContext(
        storage,
        agent_key="model_evaluation",
        operation="compare-model-runs",
        input_assets=run_paths,
        output_types=["model_comparison_report"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=300,
    ) as agent_run:
        agent_run.guard("read_asset")
        agent_run.guard("write_model_comparison_report", "model_comparison_report")
        ranked = sorted(runs, key=lambda row: float(row["content"].get("scores", {}).get("overall", 0)), reverse=True)
        winner = ranked[0] if ranked else None
        scores = [float(row["content"].get("scores", {}).get("overall", 0)) for row in runs]
        asset = ModelComparisonReport(
            title=f"Model comparison: {task_type or _common_task_type(runs)}",
            tags=["model-comparison", task_type or _common_task_type(runs)],
            content={
                "comparison_id": make_id("model_comparison", task_type or "mixed"),
                "task_type": task_type or _common_task_type(runs),
                "runs": [_run_summary(row) for row in runs],
                "winner": _run_summary(winner) if winner else {},
                "score_summary": {
                    "count": len(scores),
                    "max": max(scores) if scores else 0,
                    "min": min(scores) if scores else 0,
                    "average": round(sum(scores) / len(scores), 2) if scores else 0,
                },
                "recommendation": _recommendation(ranked),
                "created_at": utc_now(),
            },
            metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", "")},
            references=filter_project_safe_references(storage, str(project.get("project_id", "")), [row["id"] for row in runs] + [row["path"] for row in runs]),
        )
        result = _write(storage, asset)
        agent_run.succeed(output_assets=[result["path"]])
        return result


def run_model_benchmark_batch(
    storage: LocalStorage,
    *,
    task_paths: list[str | Path],
    candidates: list[dict[str, str]] | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    if not task_paths:
        raise ValueError("task_paths must not be empty")
    model_candidates = candidates or _active_model_candidates(storage)
    if not model_candidates:
        model_candidates = [{"provider": "mock", "model_name": "mock-model"}]
    run_results: list[dict[str, Any]] = []
    comparison_results: list[dict[str, Any]] = []
    with AgentExecutionContext(
        storage,
        agent_key="model_evaluation",
        operation="run-model-benchmark-batch",
        input_assets=task_paths,
        output_types=["model_benchmark_run", "model_comparison_report"],
        workspace_path=workspace_path or "",
        sla_seconds=3600,
    ) as batch_run:
        batch_run.guard("read_asset")
        for task_path in task_paths:
            task_run_paths: list[str] = []
            for candidate in model_candidates:
                result = run_model_benchmark(
                    storage,
                    task_path,
                    provider=str(candidate.get("provider") or "mock"),
                    model_name=str(candidate.get("model_name") or "mock-model"),
                )
                run_results.append(result)
                task_run_paths.append(result["path"])
            comparison = compare_model_runs(storage, task_run_paths, workspace_path=workspace_path)
            comparison_results.append(comparison)
        batch_run.succeed(
            output_assets=[*[item["path"] for item in run_results], *[item["path"] for item in comparison_results]],
            token_used=len(run_results),
        )
    return {"runs": run_results, "comparisons": comparison_results, "candidate_count": len(model_candidates)}


def create_model_routing_policy(
    storage: LocalStorage,
    *,
    comparison_paths: list[str | Path],
    status: str = "active",
    workspace_path: str | None = None,
) -> dict[str, Any]:
    if not comparison_paths:
        raise ValueError("comparison_paths must not be empty")
    comparisons = [_read_comparison(storage, item) for item in comparison_paths]
    project = _project_scope(
        storage,
        [{"id": row["id"], "path": row["path"], "type": row["asset"].get("type", "")} for row in comparisons],
        workspace_path=workspace_path,
    )
    task_routes: dict[str, Any] = {}
    fallbacks: dict[str, list[dict[str, Any]]] = {}
    tradeoffs: dict[str, Any] = {}
    for row in comparisons:
        content = row["content"]
        task_type = str(content.get("task_type") or "generate")
        runs = content.get("runs", []) if isinstance(content.get("runs", []), list) else []
        ranked = sorted(runs, key=lambda item: float(item.get("overall", 0)) if isinstance(item, dict) else 0, reverse=True)
        winner = content.get("winner", {}) if isinstance(content.get("winner", {}), dict) else {}
        if not winner and ranked:
            winner = ranked[0]
        task_routes[task_type] = {
            "provider": winner.get("provider", "mock"),
            "model_name": winner.get("model_name", "mock-model"),
            "source_comparison_path": row["path"],
            "overall": winner.get("overall", 0),
            "latency_ms": winner.get("latency_ms", 0),
            "reason": content.get("recommendation", ""),
        }
        fallbacks[task_type] = [
            {
                "provider": item.get("provider", ""),
                "model_name": item.get("model_name", ""),
                "overall": item.get("overall", 0),
                "latency_ms": item.get("latency_ms", 0),
            }
            for item in ranked[1:4]
            if isinstance(item, dict)
        ]
        tradeoffs[task_type] = {
            "score_summary": content.get("score_summary", {}),
            "selection_rule": "highest overall benchmark score, then latest active policy",
        }
    with AgentExecutionContext(
        storage,
        agent_key="model_evaluation",
        operation="create-model-routing-policy",
        input_assets=comparison_paths,
        output_types=["model_routing_policy"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
        run.guard("write_model_routing_policy", "model_routing_policy")
        asset = ModelRoutingPolicy(
            title=f"Model routing policy {utc_now()}",
            tags=["model-routing", status],
            content={
                "policy_id": make_id("model_routing_policy", str(project.get("project_id") or "global")),
                "task_routes": task_routes,
                "fallbacks": fallbacks,
                "cost_quality_tradeoffs": tradeoffs,
                "effective_from": utc_now(),
                "status": status,
                "created_at": utc_now(),
            },
            metadata={"project_id": project.get("project_id", ""), "workspace_path": project.get("workspace_path", ""), "status": status},
            references=filter_project_safe_references(
                storage,
                str(project.get("project_id", "")),
                [row["id"] for row in comparisons] + [row["path"] for row in comparisons],
            ),
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]])
        return result


def resolve_model_route(
    storage: LocalStorage,
    *,
    task_type: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    policy = _latest_active_routing_policy(storage, project_id=project_id)
    if not policy:
        return {"provider": "mock", "model_name": "mock-model", "source": "default"}
    content = policy.get("content", {}) if isinstance(policy.get("content", {}), dict) else {}
    routes = content.get("task_routes", {}) if isinstance(content.get("task_routes", {}), dict) else {}
    route = routes.get(task_type) or routes.get("generate") or {}
    if not isinstance(route, dict) or not route:
        return {"provider": "mock", "model_name": "mock-model", "source": "default"}
    return {**route, "source": "model_routing_policy", "policy_id": content.get("policy_id", ""), "policy_path": policy.get("path", "")}


def create_prompt_version(
    storage: LocalStorage,
    *,
    prompt_id: str,
    version: str,
    task_type: str,
    template: str,
    status: str = "draft",
) -> dict[str, Any]:
    with AgentExecutionContext(
        storage,
        agent_key="model_evaluation",
        operation="create-prompt-version",
        output_types=["prompt_version"],
        sla_seconds=300,
    ) as run:
        run.guard("write_prompt_version", "prompt_version")
        asset = PromptVersion(
            title=f"{prompt_id} {version}",
            tags=["prompt-version", task_type, status],
            content={
                "prompt_id": prompt_id,
                "version": version,
                "task_type": task_type,
                "template": template,
                "status": status,
                "created_at": utc_now(),
            },
            metadata={"task_type": task_type},
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]])
        return result


def create_prompt_regression_report(
    storage: LocalStorage,
    *,
    prompt_id: str,
    baseline_version: str,
    candidate_version: str,
    benchmark_runs: list[str],
) -> dict[str, Any]:
    run_rows = [_read_run(storage, item) for item in benchmark_runs]
    baseline_scores = [float(row["content"].get("scores", {}).get("overall", 0)) for row in run_rows if baseline_version in str(row["content"].get("raw_output", ""))]
    candidate_scores = [float(row["content"].get("scores", {}).get("overall", 0)) for row in run_rows if candidate_version in str(row["content"].get("raw_output", ""))]
    recommendation = "promote" if (sum(candidate_scores) / len(candidate_scores) if candidate_scores else 0) >= (sum(baseline_scores) / len(baseline_scores) if baseline_scores else 0) else "keep_baseline"
    with AgentExecutionContext(
        storage,
        agent_key="model_evaluation",
        operation="create-prompt-regression-report",
        input_assets=benchmark_runs,
        output_types=["prompt_regression_report"],
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
        run.guard("write_prompt_regression_report", "prompt_regression_report")
        asset = PromptRegressionReport(
            title=f"Prompt regression {prompt_id}: {baseline_version} -> {candidate_version}",
            tags=["prompt-regression", recommendation],
            content={
                "prompt_id": prompt_id,
                "baseline_version": baseline_version,
                "candidate_version": candidate_version,
                "benchmark_runs": benchmark_runs,
                "score_delta": round((sum(candidate_scores) / len(candidate_scores) if candidate_scores else 0) - (sum(baseline_scores) / len(baseline_scores) if baseline_scores else 0), 2),
                "recommendation": recommendation,
                "created_at": utc_now(),
            },
            references=benchmark_runs,
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]])
        return result


def list_model_evaluation_assets(storage: LocalStorage, *, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") not in EVALUATION_TYPES:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "id": data.get("id", ""),
                "type": data.get("type", ""),
                "title": data.get("title") or data.get("name", ""),
                "provider": content.get("provider") or metadata.get("provider", ""),
                "model_name": content.get("model_name") or metadata.get("model_name", ""),
                "task_type": content.get("task_type", ""),
                "status": content.get("status", ""),
                "scores": content.get("scores", {}),
                "score": content.get("scores", {}).get("overall", 0) if isinstance(content.get("scores", {}), dict) else 0,
                "cost_estimate": content.get("cost_estimate", {}),
                "latency_ms": content.get("latency_ms", ""),
                "recommendation": content.get("recommendation", ""),
                "task_routes": content.get("task_routes", {}),
                "updated_at": data.get("updated_at", ""),
            }
        )
        if len(rows) >= limit:
            break
    return sorted(rows, key=lambda row: row.get("updated_at", ""), reverse=True)


def _run_adapter(adapter: ModelAdapter, task: Any) -> dict[str, Any]:
    task_type = str(task.content.get("task_type", "generate"))
    context = {"benchmark_task": task.content, "input_assets": task.content.get("input_assets", [])}
    prompt = str(task.content.get("prompt_template", ""))
    if task_type in {"review", "quality_review", "chapter_review"}:
        return adapter.review(prompt, context)
    if task_type in {"analysis", "decomposition"}:
        return adapter.analyze(prompt, context)
    if task_type in {"revision", "revise"}:
        return adapter.revise(prompt, {}, context)
    return adapter.generate(prompt, context)


def _model_for_benchmark(task_type: str, *, provider: str, model_name: str) -> ModelAdapter:
    normalized_provider = (provider or "mock").strip()
    normalized_model = (model_name or "").strip()
    if normalized_provider in {"mock", "local", "local-rules", "offline"}:
        return model_from_env(task_type, env={**os.environ, "NOVEL_FORGE_MODEL_PROVIDER": "mock"})
    env = dict(os.environ)
    env["NOVEL_FORGE_MODEL_PROVIDER"] = normalized_provider
    if normalized_model:
        env["NOVEL_FORGE_MODEL_NAME"] = normalized_model
    operation_key = task_type.upper().replace("-", "_")
    env[f"NOVEL_FORGE_MODEL_PROVIDER_{operation_key}"] = normalized_provider
    if normalized_model:
        env[f"NOVEL_FORGE_MODEL_NAME_{operation_key}"] = normalized_model
    return model_from_env(task_type, env=env)


def _validate_expected(expected_output_type: Any, raw_output: dict[str, Any]) -> dict[str, Any]:
    expected = str(expected_output_type or "generate")
    if expected in {"generate", "review", "analyze", "revise"}:
        return validate_model_output(expected, raw_output)
    return raw_output


def _score_output(task: Any, output: dict[str, Any], *, status: str, latency_ms: float) -> dict[str, Any]:
    if status != "succeeded":
        return {"overall": 0, "schema": 0, "latency": 0, "output_chars": 0}
    text = str(output.get("text") or output.get("summary") or output)
    rubric = task.content.get("rubric", {}) if isinstance(task.content.get("rubric", {}), dict) else {}
    schema_score = 100 if output else 0
    length_target = int(rubric.get("target_chars", 800))
    length_score = min(100, int((len(text) / max(1, length_target)) * 100))
    latency_score = max(0, 100 - int(latency_ms / 1000))
    overall = round(schema_score * 0.45 + length_score * 0.35 + latency_score * 0.2, 2)
    return {"overall": overall, "schema": schema_score, "length": length_score, "latency": latency_score, "output_chars": len(text)}


def _default_capabilities(task_types: list[str]) -> dict[str, Any]:
    return {
        "task_types": task_types,
        "supports_json_output": True,
        "supports_long_context": False,
        "supports_batch": False,
        "local_safe": True,
    }


def _default_rubric(task_type: str) -> dict[str, Any]:
    return {
        "task_type": task_type,
        "dimensions": ["schema_validity", "instruction_following", "usefulness", "latency"],
        "weights": {"schema_validity": 0.45, "instruction_following": 0.2, "usefulness": 0.25, "latency": 0.1},
        "target_chars": 800,
    }


def _default_prompt_template(task_type: str) -> str:
    return f"Run a deterministic {task_type} benchmark for Novel Forge using the provided input assets."


def _read_run(storage: LocalStorage, value: str | Path) -> dict[str, Any]:
    path = resolve_path(storage.root, value)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "model_benchmark_run":
        raise ValueError(f"path must point to a model_benchmark_run asset: {value}")
    return {"path": _display_path(storage.root, path), "id": data.get("id", ""), "asset": data, "content": data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}}


def _read_comparison(storage: LocalStorage, value: str | Path) -> dict[str, Any]:
    path = resolve_path(storage.root, value)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "model_comparison_report":
        raise ValueError(f"path must point to a model_comparison_report asset: {value}")
    return {"path": _display_path(storage.root, path), "id": data.get("id", ""), "asset": data, "content": data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}}


def _run_summary(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    content = row["content"]
    return {
        "id": row["id"],
        "path": row["path"],
        "provider": content.get("provider", ""),
        "model_name": content.get("model_name", ""),
        "status": content.get("status", ""),
        "overall": content.get("scores", {}).get("overall", 0) if isinstance(content.get("scores", {}), dict) else 0,
        "latency_ms": content.get("latency_ms", 0),
    }


def _common_task_type(runs: list[dict[str, Any]]) -> str:
    values = {str(row["content"].get("task_type", "")) for row in runs if row["content"].get("task_type")}
    return values.pop() if len(values) == 1 else "mixed"


def _recommendation(ranked: list[dict[str, Any]]) -> str:
    if not ranked:
        return "needs_more_runs"
    winner = _run_summary(ranked[0])
    return f"prefer {winner.get('provider', '')}/{winner.get('model_name', '')} for this benchmark until a stronger run is recorded"


def _estimate_run_cost(storage: LocalStorage, *, provider: str, model_name: str, scores: dict[str, Any], task: Any) -> dict[str, Any]:
    profile = _model_profile(storage, provider=provider, model_name=model_name)
    cost_profile = profile.get("content", {}).get("cost_profile", {}) if isinstance(profile.get("content", {}), dict) else {}
    input_per_1k = float(cost_profile.get("input_per_1k", 0) or 0)
    output_per_1k = float(cost_profile.get("output_per_1k", 0) or 0)
    prompt_chars = len(str(task.content.get("prompt_template", ""))) + len(str(task.content.get("input_assets", [])))
    output_chars = int(scores.get("output_chars", 0) or 0)
    input_tokens = max(1, int(prompt_chars / 4))
    output_tokens = max(1, int(output_chars / 4))
    estimated = round((input_tokens / 1000) * input_per_1k + (output_tokens / 1000) * output_per_1k, 6)
    return {
        "currency": cost_profile.get("currency", "USD"),
        "input_tokens_estimate": input_tokens,
        "output_tokens_estimate": output_tokens,
        "cost": estimated,
        "source": "model_profile.cost_profile" if cost_profile else "default_zero_cost",
    }


def _model_profile(storage: LocalStorage, *, provider: str, model_name: str) -> dict[str, Any]:
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "model_profile":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if str(content.get("provider", "")) == provider and str(content.get("model_name", "")) == model_name:
            return data
    return {"content": {"cost_profile": {"input_per_1k": 0, "output_per_1k": 0, "currency": "USD"}}}


def _active_model_candidates(storage: LocalStorage) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "model_profile":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        status = str(content.get("status", "") or data.get("metadata", {}).get("status", ""))
        if status not in {"active", "candidate", "default"}:
            continue
        provider = str(content.get("provider") or data.get("metadata", {}).get("provider") or "").strip()
        model_name = str(content.get("model_name") or data.get("metadata", {}).get("model_name") or "").strip()
        if provider and model_name:
            candidates.append({"provider": provider, "model_name": model_name})
    return candidates[:12]


def _latest_active_routing_policy(storage: LocalStorage, *, project_id: str | None = None) -> dict[str, Any] | None:
    policies: list[dict[str, Any]] = []
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "model_routing_policy":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if content.get("status") != "active":
            continue
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        policies.append({**data, "path": _display_path(storage.root, path)})
    return sorted(policies, key=lambda item: str(item.get("updated_at", "")), reverse=True)[0] if policies else None


def _asset_ref(storage: LocalStorage, value: str | Path) -> dict[str, str]:
    path = resolve_path(storage.root, value)
    if path.exists() and path.is_file():
        asset = storage.read_asset(path)
        return {"id": asset.id, "type": asset.type, "title": asset.title or asset.name, "path": _display_path(storage.root, path)}
    return {"id": str(value), "type": "", "title": "", "path": str(value)}


def _project_scope(storage: LocalStorage, refs: list[dict[str, str]], *, workspace_path: str | None = None) -> dict[str, Any]:
    if workspace_path:
        return project_scope_from_asset(storage, {}, workspace_path=workspace_path)
    for ref in refs:
        path = ref.get("path", "")
        if not path:
            continue
        try:
            asset = storage.read_asset(resolve_path(storage.root, path))
        except Exception:
            continue
        project = project_scope_from_asset(storage, asset, input_path=path)
        if project.get("project_id") or project.get("workspace_path"):
            return project
    return {"project_id": "", "workspace_path": "", "title": ""}


def _write(
    storage: LocalStorage,
    asset: ModelProfile | ModelBenchmarkTask | ModelBenchmarkRun | ModelComparisonReport | ModelRoutingPolicy | PromptVersion | PromptRegressionReport,
) -> dict[str, Any]:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "id": asset.id, "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
