# Canon Re-extraction Governance

Migration `0031_canon_reextraction_governance` freezes maximum generations, total
cost, deadline, same-digest/no-progress limits and escalation policy. Each generation
stores extraction/proposal/change/conflict digests. Re-extraction Proposal consumes
its own generation Extraction, not generation 1. Generation steps are registered in
the original Root Saga as `canon_extraction:gN` and `canon_proposal:gN`.

No-progress or deadline exhaustion moves to `WAITING_OPERATOR`; generation caps fail
before a decision Attempt is admitted. Existing DEFER/reopen and per-change Approval
remain authoritative. Evidence: policy unit tests and PostgreSQL generation-2 gate
recovery/timeline proof. Commit `0d7da86`.
