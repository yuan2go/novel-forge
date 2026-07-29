# Long-form Recap Operation

`longform.recap@1.0.0` is a governed observer Operation. It analyzes frozen
long-form state and emits proposals; it cannot change BookPlan, VolumePlan,
ArcPlan, ChapterPlan, Canon, or prose.

## Triggers

The deterministic trigger policy supports chapter cadence, Chapter Group
completion, Arc/Volume checkpoint, manual request, worsening Reader Outcome,
Canon risk, Promise/Reward debt, declining quality, and Book Authority request.

The V1 Book Scheduler proves the cadence path:

```text
Chapter terminal
→ Reader Outcome terminal
→ cadence due
→ longform.recap Operation
→ Longform Recap / Deviation Report / Adjustment Proposal
→ Book Authority checkpoint decision
```

## Frozen input and output

The Book root stores immutable version references for BookDesign, BookPlan,
VolumePlan, ArcPlan, Character State, Foreshadowing State, Quality Trend, Reward
Ledger, and Promise Ledger. Recap also freezes the Chapter Canon and resulting
Reader State AssetVersions.

Outputs:

- `longform_recap`;
- `longform_deviation_report`;
- `plan_adjustment_proposal`;
- optional `replan_request` for blocking deviations.

Deviation types cover plot/arc/character drift, character disappearance, power
inflation, Canon/timeline conflict, foreshadowing/promise debt, reward cadence,
repetition/style/pacing drift, antagonist pressure, protagonist charm, Reader
confusion, and quality decline. Only evidence-supported deviations are emitted;
the enum set is not populated with empty records.

`plan_adjustment_proposal.decision_status` is `AUTHORITY_PENDING` and
`mutates_plan=false`. Book Design Authority must accept/reject, request impact
analysis, or create a separate Replan Operation.

V1 Recap computation is deterministic and storage-free. The shared Authority
handler runtime still provides Attempt, lease/fence, immutable output,
idempotency, retry/recovery, evidence, outbox, and Projection semantics.
