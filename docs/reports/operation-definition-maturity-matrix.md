# OperationDefinition Maturity Matrix

Generated catalog source: `docs/reports/postgresql-operation-definition-catalog.json`, source commit `2e506f1`.

| Definition status | Count | Meaning |
|---|---:|---|
| candidate | 65 | documented target, no mapped legacy entrypoint or handler |
| mapped | 17 | legacy entrypoint mapped, no concrete Authority handler |
| handler_bound | 0 | no catalog record remains in this transient state |
| enabled | 0 | enabled without committed integration proof |
| integration_proven | 42 | chapter root plus eighteen nodes, 22 content definitions, and `canon.change.approve` pass PostgreSQL Authority tests; Canon re-extraction is a recovery generation of existing nodes |
| production_verified | 0 | no real-provider production proof |

Each record separates `documented`, `implemented`, `handler_bound`, `integration_proven`, `real_provider_proven`, and `longform_proven`. Provider v2 scripted proof, policy compilation, calibration fixtures, and Canon recovery do not increase the count or imply Provider/long-form proof.

The 22 Content Definitions additionally report `product_entrypoint_integrated=true`
and expose API, Agent capability, and Workflow binding metadata. This does not change
their `integration_proven` maturity or imply Provider/long-form proof.
