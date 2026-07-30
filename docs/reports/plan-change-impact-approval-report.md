# Plan Change, Impact and Approval

Status: `documented=true`, `implemented=true`, `handler_bound=true`,
`fixture_proven=true`, `integration_proven=true`,
`real_provider_proven=false`, `longform_proven=false`,
`production_verified=false`.

The governed chain is:

```text
Evidence AssetVersion
→ plan_change.propose
→ field-level semantic diff
→ PlanChangeProposal AssetVersion
→ plan_change.approve
→ Authority Decision AssetVersion
→ plan_change.activate
→ Story Design activation
→ typed plan binding
→ dependency-edge impact propagation
→ audit / outbox
```

Diffs explicitly classify objective, required/forbidden event, payoff,
character delta, Arc contribution, chapter range, EndingContract, Canon
dependency and quality-target changes. Frozen or high-risk fields require a
formal Authority decision. Executed plans are retcon-only.

Impact uses the concrete recursive `asset_dependency_edge` graph. It never
invalidates every asset of a type. Scope policy is:

- Executed: history stays current and is not automatically rewritten.
- Frozen: mark impacted and require approval.
- Planned: mark stale and require revalidation/regeneration.
- Speculative: mark stale and allow a bounded candidate regeneration policy.

Activation is recoverably atomic. A failure after semantic activation but
before typed binding leaves the proposal `ACTIVATION_PENDING`; replay verifies
the active semantic version, converges the single typed Active Plan, records
impacts and emits evidence. Database unique constraints prevent two active
versions for the same project, book and logical key.

Evidence:

- `tests.unit.test_plan_change_authority`
- `tests.integration.test_plan_change_authority_postgres`
- injected interruption at `after_plan_activation_before_binding`;
- replay converges without a duplicate active plan;
- exact dependent Planned plan becomes stale;
- exact dependent Executed plan remains current;
- governed revalidation restores current freshness.
