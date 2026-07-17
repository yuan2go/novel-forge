# OperationDefinition Maturity Matrix

Generated catalog source: `docs/reports/postgresql-operation-definition-catalog.json`, source commit `1ef93fa`.

| Definition status | Count | Meaning |
|---|---:|---|
| candidate | 65 | documented target, no mapped legacy entrypoint or handler |
| mapped | 17 | legacy entrypoint mapped, no concrete Authority handler |
| handler_bound | 22 | storage-free handler and typed contracts exist; disabled pending integration |
| enabled | 0 | enabled without committed integration proof |
| integration_proven | 10 | chapter root plus nine nodes pass PostgreSQL Authority tests |
| production_verified | 0 | no real-provider production proof |

Each record separates `documented`, `implemented`, `handler_bound`, `integration_proven`, `real_provider_proven`, and `longform_proven`. The last two remain false across this round.
