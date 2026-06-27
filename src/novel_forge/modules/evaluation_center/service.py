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
                "latency_ms": content.get("latency_ms", ""),
                "recommendation": content.get("recommendation", ""),
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


def _write(storage: LocalStorage, asset: ModelProfile | ModelBenchmarkTask | ModelBenchmarkRun | ModelComparisonReport | PromptVersion | PromptRegressionReport) -> dict[str, Any]:
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
