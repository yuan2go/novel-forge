# Reader Outcome Operation

`reader_outcome.evaluate@1.0.0` is a governed post-Chapter business Operation.

## Call path

```text
Book Authority
→ BookFollowupAuthorityApplication.admit
→ Command Kernel / Operation
→ shared ContentAuthorityScheduler
→ Attempt / Lease / Fence
→ ReaderOutcomeHandler
→ ExternalEffect-backed model port
→ ProductionExecutionGateway
→ frozen RouteSnapshot / qualified Backend
→ structured output validation
→ Reader Outcome domain gate
→ immutable AssetVersions + evidence + outbox
→ read-only Projection
```

Required frozen inputs include the final draft, ChapterPlan, BookDesign, Canon
snapshot, Reader contract/state, evaluation profile, and model strategy
versions. The production model adapter records Provider/model, request and prompt
identity, Attempt, provider request, usage, cost, receipt, status, and error
classification through the existing ExternalEffect and ledger tables.

Outputs are:

- `reader_outcome_report`;
- `reader_state_transition`;
- `reader_issue_set`.

The structured Reader State contains continue intent, curiosity, satisfaction,
confusion, trust, character attachment, antagonist pressure, promise
expectation, payoff satisfaction, drop risk, and repetition fatigue. The gate is
explainable and does not reduce these dimensions to one score:

```text
PASS
PASS_WITH_WARNINGS
REVISION_RECOMMENDED
REVISION_REQUIRED
HUMAN_REVIEW_REQUIRED
BLOCKED
```

The handler cannot modify a draft. Revision is a separate Authority decision and
Operation. Invalid model shape fails domain execution; a backend success alone
cannot materialize the report. Retry, cancellation, UNKNOWN reconciliation,
receipt, and stale-fence behavior are supplied by the shared execution plane.

Current evidence uses the scripted Provider through the real PEP seam. No real
Provider calibration or production proof is claimed.
