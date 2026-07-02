# Provider Hard-stop Report

This proof uses runnable local provider adapters through `GuardedModelAdapter`, plus the OpenAI-compatible stream reader path for streaming cancel evidence. It does not rely only on mocks.

Evidence status: `passed`
Covered dimensions: `4/4`
Failed model calls: `16`

| Scenario | Status | Accepted Draft Written | Canonical Chapter Written | Message |
|---|---|---:|---:|---|
| token_over_budget | failed_closed | False | False | provider token cutoff exceeded: used 130, limit 100 |
| cost_over_budget | failed_closed | False | False | provider cost cutoff exceeded: estimated 0.02 USD, limit 0.001 |
| timeout | failed_closed | False | False | provider timeout exceeded: elapsed 22ms, limit 1ms |
| cancel | failed_closed | False | False | provider execution cancellation requested |
| provider_error | failed_closed | False | False | local provider forced failure |
| streaming_cancel | failed_closed | False | False | provider execution cancellation requested |
| retry_exhausted_dead_letter | dead_letter | False | False | [{'queue_path': 'data/runs/agent-dispatch-d67a7c5b038a9e64.json', 'error': 'ValueError: agent operation requires at least one input asset: release_package'}] |

## Provider Guard Summary

```json
{
  "provider_guard_gate_count": 32,
  "failed_provider_guard_count": 19,
  "failed_model_call_count": 16,
  "required_hard_stop_dimension_count": 4,
  "covered_hard_stop_dimension_count": 4,
  "dimension_counts": {
    "token": 4,
    "cost": 3,
    "cancel": 6,
    "timeout": 3
  },
  "missing_dimensions": []
}
```

## Result

- token, cost, timeout, cancel and streaming cancel fail closed before accepted/canonical chapter writes.
- provider error is recorded as a failed model call and agent failure report.
- retry exhaustion is represented by a dead-letter dispatch queue item.
