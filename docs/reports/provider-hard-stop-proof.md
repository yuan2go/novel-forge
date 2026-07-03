# Provider Hard-stop Proof

日期：2026-07-03

## 证明范围

Phase 11 固定 provider runtime 的 hard-stop 证据边界：

- token limit；
- cost limit；
- timeout；
- cancel；
- failed model call log；
- gate result；
- no silent retry；
- no silent fallback。

## 证据矩阵

| 维度 | 证明方式 | 证据 |
| -- | -- | -- |
| Token limit | `ProviderRuntimeGuard(max_total_tokens=100)` 触发 `provider_token_cutoff` | `tests/unit/test_provider_hard_stop_proof.py` |
| Cost limit | `ProviderRuntimeGuard(max_cost=0.001)` 触发 `provider_cost_cutoff` | 同上 |
| Timeout | `ProviderRuntimeGuard(timeout_ms=20)` 触发 `provider_timeout` | 同上 |
| Cancel | `ProviderRuntimeGuard(cancel_file=...)` 触发 `provider_cancel_requested` | 同上 |
| Gate evidence | 每个 hard-stop 写入 `gate_result` | `record_gate_result` |
| Failed model call | 每个 hard-stop 写入 failed `model_call_log` | `record_model_call_log` |
| Runtime proof report | `provider_hard_stop_evidence_report` 返回 `status=passed` 且 4/4 covered | `src/novel_forge/modules/runtime_policy/service.py` |
| Retry boundary | hard-stop 后只记录一次 failed model call | `test_gateway_hard_stop_does_not_retry_or_fallback_silently` |
| Fallback boundary | route resolution 保留 fallback，但 hard-stop 不自动调用 fallback provider | 同上 |

## 取舍

当前系统选择 fail-closed：

1. provider hard-stop 后不自动重试；
2. provider hard-stop 后不自动 fallback；
3. fallback 信息可以在 ModelRouteResolution 中观察；
4. 是否重试或 fallback 应由 Agent Center / operator policy 明确触发。

这样避免成本、token 和版权边界被“自动补救”路径绕过。

## 测试

| 命令 | 结果 |
| -- | -- |
| `python3 -m unittest tests.unit.test_provider_hard_stop_proof` | 2 tests OK |
| `python3 -m unittest tests.unit.test_provider_runtime_guard tests.unit.test_runtime_policy` | 待最终 Phase 12 全量重跑 |
