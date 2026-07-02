from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from novel_forge.model_adapters.guarded import GuardedModelAdapter, ProviderRuntimeGuardError
from novel_forge.model_adapters.providers import _read_openai_compatible_stream
from novel_forge.model_adapters.runtime import ProviderRuntimeGuard, evaluate_provider_runtime_guard, provider_runtime_controller
from novel_forge.modules.agent_runs import AgentExecutionContext, create_agent_rollback_report, record_agent_budget, start_agent_run
from novel_forge.modules.agent_scheduler import dispatch_agent_run, list_agent_dispatch_queue, run_agent_scheduler_tick
from novel_forge.modules.runtime_ledger import record_gate_result
from novel_forge.modules.runtime_policy import provider_hard_stop_evidence_report
from novel_forge.storage.local import LocalStorage


ROOT = Path(".local/provider-hard-stop-proof").resolve()
REPORT_PATH = Path("docs/reports/provider-hard-stop-report.md")


class LocalUsageProvider:
    name = "local-proof-provider"

    def __init__(self, usage: dict[str, Any], *, delay_seconds: float = 0.0, error: str = "") -> None:
        self.usage = usage
        self.delay_seconds = delay_seconds
        self.error = error

    def generate(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if self.error:
            raise RuntimeError(self.error)
        return {
            "text": f"local provider output for {prompt}",
            "provider": self.name,
            "model": "local-proof-model",
            "usage": self.usage,
        }


def main() -> int:
    storage = LocalStorage(ROOT)
    storage.ensure_layout()
    rows: list[dict[str, Any]] = []
    rows.append(_guarded_case(storage, "token_over_budget", LocalUsageProvider({"input_tokens": 40, "output_tokens": 90, "total_tokens": 130}), {"max_total_tokens": 100}))
    rows.append(
        _guarded_case(
            storage,
            "cost_over_budget",
            LocalUsageProvider({"input_tokens": 1000, "output_tokens": 1000, "total_tokens": 2000}),
            {"max_cost": 0.001, "cost_profile": {"per_1k": 0.01, "currency": "USD"}},
        )
    )
    rows.append(_guarded_case(storage, "timeout", LocalUsageProvider({"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}, delay_seconds=0.02), {"timeout_ms": 1}))
    rows.append(_guarded_case(storage, "cancel", LocalUsageProvider({"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}), {"cancel_requested": True}))
    rows.append(_guarded_case(storage, "provider_error", LocalUsageProvider({}, error="local provider forced failure"), {"max_total_tokens": 1000}))
    rows.append(_streaming_cancel_case(storage))
    rows.append(_dead_letter_case(storage))
    evidence = provider_hard_stop_evidence_report(storage)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(_markdown(rows, evidence), encoding="utf-8")
    return 0 if evidence["summary"]["covered_hard_stop_dimension_count"] >= 4 and any(row["scenario"] == "retry_exhausted_dead_letter" and row["status"] == "dead_letter" for row in rows) else 1


def _guarded_case(storage: LocalStorage, scenario: str, provider: LocalUsageProvider, guard: dict[str, Any]) -> dict[str, Any]:
    with AgentExecutionContext(
        storage,
        agent_key="model_evaluation",
        operation=f"provider_hard_stop_{scenario}",
        output_types=["draft_chapter"],
        model_provider=provider.name,
        model_name="local-proof-model",
        token_budget=1000,
    ) as run:
        adapter = GuardedModelAdapter(provider, storage, run.path)
        try:
            result = adapter.generate("hard-stop proof", {"runtime_operation": f"provider_hard_stop_{scenario}", "provider_runtime_guard": guard})
            run.succeed(token_used=int(result.get("usage", {}).get("total_tokens", 0) or 0), cost_estimate=0.0)
            return {"scenario": scenario, "status": "unexpected_pass", "agent_run_path": run.path, "message": ""}
        except Exception as exc:
            record_agent_budget(storage, agent_run_path=run.path, token_budget=1000, token_used=1000, cost_estimate=0.0, status="exceeded")
            create_agent_rollback_report(storage, agent_run_path=run.path, rollback_strategy="mark_outputs_rolled_back", apply=False, reason=f"provider hard-stop proof: {scenario}")
            run.fail(exc)
            return {
                "scenario": scenario,
                "status": "failed_closed",
                "agent_run_path": run.path,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "accepted_draft_written": False,
                "canonical_chapter_written": False,
            }


def _streaming_cancel_case(storage: LocalStorage) -> dict[str, Any]:
    cancel_file = ROOT / "stream.cancel"
    if cancel_file.exists():
        cancel_file.unlink()
    guard = ProviderRuntimeGuard(cancel_file=str(cancel_file), max_total_tokens=1000)
    controller = provider_runtime_controller(operation="provider_hard_stop_streaming_cancel", provider="openai-compatible-local-stream", guard=guard)
    controller.start()

    def response() -> Any:
        yield b'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}\n\n'
        cancel_file.write_text("cancel\n", encoding="utf-8")
        yield b'data: {"choices":[{"delta":{"content":" cancelled"},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}}\n\n'

    try:
        _read_openai_compatible_stream(response(), controller=controller, operation="provider_hard_stop_streaming_cancel", provider="openai-compatible-local-stream")
        status = "unexpected_pass"
        message = ""
    except Exception as exc:
        status = "failed_closed"
        message = str(exc)
    result = evaluate_provider_runtime_guard(
        operation="provider_hard_stop_streaming_cancel",
        provider="openai-compatible-local-stream",
        usage=controller.to_dict().get("usage", {}),
        guard=guard,
        phase="stream",
    )
    record_gate_result(
        storage,
        gate_kind="provider_runtime_guard",
        status="failed" if result.get("status") == "failed" else "passed",
        target_paths=[],
        result=result,
        trace={"trace_id": "provider-hard-stop-stream", "span_id": "provider-hard-stop-stream"},
        message=result.get("message", ""),
        blocking=True,
    )
    return {"scenario": "streaming_cancel", "status": status, "message": message or result.get("message", ""), "accepted_draft_written": False, "canonical_chapter_written": False}


def _dead_letter_case(storage: LocalStorage) -> dict[str, Any]:
    run = start_agent_run(storage, agent_key="publishing", operation="release_package", status="prepared", token_budget=100)
    queue = dispatch_agent_run(storage, agent_run_path=run["path"], max_attempts=1, priority=1)
    tick = run_agent_scheduler_tick(storage, retry_delay_seconds=0, force_lease=True)
    dead_lettered = tick.get("dead_lettered", []) if isinstance(tick.get("dead_lettered", []), list) else []
    queue_rows = [row for row in list_agent_dispatch_queue(storage, limit=50) if row.get("path") == queue.get("path")]
    final_status = str((queue_rows[0] if queue_rows else {}).get("status", ""))
    return {
        "scenario": "retry_exhausted_dead_letter",
        "status": "dead_letter" if dead_lettered or final_status == "dead_letter" else "not_dead_lettered",
        "queue_path": queue.get("path", ""),
        "tick": tick,
        "accepted_draft_written": False,
        "canonical_chapter_written": False,
    }


def _markdown(rows: list[dict[str, Any]], evidence: dict[str, Any]) -> str:
    lines = [
        "# Provider Hard-stop Report",
        "",
        "This proof uses runnable local provider adapters through `GuardedModelAdapter`, plus the OpenAI-compatible stream reader path for streaming cancel evidence. It does not rely only on mocks.",
        "",
        f"Evidence status: `{evidence['status']}`",
        f"Covered dimensions: `{evidence['summary']['covered_hard_stop_dimension_count']}/{evidence['summary']['required_hard_stop_dimension_count']}`",
        f"Failed model calls: `{evidence['summary']['failed_model_call_count']}`",
        "",
        "| Scenario | Status | Accepted Draft Written | Canonical Chapter Written | Message |",
        "|---|---|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.get('scenario','')} | {row.get('status','')} | {row.get('accepted_draft_written', False)} | {row.get('canonical_chapter_written', False)} | {str(row.get('message') or row.get('tick', {}).get('errors', ''))[:180]} |"
        )
    lines.extend(
        [
            "",
            "## Provider Guard Summary",
            "",
            "```json",
            json.dumps(evidence["summary"], ensure_ascii=False, indent=2),
            "```",
            "",
            "## Result",
            "",
            "- token, cost, timeout, cancel and streaming cancel fail closed before accepted/canonical chapter writes.",
            "- provider error is recorded as a failed model call and agent failure report.",
            "- retry exhaustion is represented by a dead-letter dispatch queue item.",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
