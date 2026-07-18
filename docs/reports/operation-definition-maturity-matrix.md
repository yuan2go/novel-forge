# OperationDefinition Maturity Matrix

Generated catalog source: `docs/reports/postgresql-operation-definition-catalog.json`, source commit `de738d6`.

| Definition status | Count | Meaning |
|---|---:|---|
| candidate | 65 | documented target, no mapped legacy entrypoint or handler |
| mapped | 17 | legacy entrypoint mapped, no concrete Authority handler |
| handler_bound | 0 | no catalog record remains in this transient state |
| enabled | 0 | enabled without committed integration proof |
| integration_proven | 35 | chapter root plus twelve nodes, and 22 content definitions, pass PostgreSQL Authority tests |
| production_verified | 0 | no real-provider production proof |

Each record separates `documented`, `implemented`, `handler_bound`, `integration_proven`, `real_provider_proven`, and `longform_proven`. The last two remain false across this round.

The 22 Content Definitions additionally report `product_entrypoint_integrated=true`
and expose API, Agent capability, and Workflow binding metadata. This does not change
their `integration_proven` maturity or imply Provider/long-form proof.
