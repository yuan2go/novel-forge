# Agent Center Hardening Report

Status: `blocked`
Health score: `85`

| Capability | Present | Evidence Count / Status |
|---|---:|---|
| run graph | yes | 19 nodes |
| gate timeline | yes | 29 rows |
| checkpoint list | yes | 51 rows |
| budget burn | yes | {"count": 5, "exceeded_count": 5, "token_used": 5000, "cost_estimate": 0.0} |
| retry controls | yes | 3 rows |
| dead-letter queue | yes | 3 rows |
| rollback preview | yes | 5 rows |
| SLA / duration tracking | yes | 19 rows |
| evidence drawer | yes | 160 rows |
| operation coverage | yes | 37 contracts |

## Readiness Checks

- operation_contracts: passed - Agent operation contracts are registered
- dispatch_queue: passed - Agent queue or run evidence exists
- checkpoints: passed - Agent checkpoints exist
- gates: passed - Agent gate evidence exists
- budgets: passed - Agent budget evidence exists
- rollback: passed - Rollback evidence exists or no failures need rollback

## Recommendations

- recover or cancel blocked dispatch queue items before scheduling more autonomous work
- create rollback reports and recovery instructions for failed Agent runs

## Snapshot Summary

```json
{
  "health_score": 85,
  "agent_run_count": 19,
  "queue_count": 3,
  "blocked_queue_count": 3,
  "checkpoint_count": 51,
  "gate_count": 29,
  "budget_count": 5,
  "failure_count": 28,
  "rollback_count": 5,
  "contract_count": 37,
  "queue_by_status": {
    "dead_letter": 3
  }
}
```
