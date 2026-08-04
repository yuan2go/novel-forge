# PostgreSQL Authority Cutover Hardening Findings

This report records implementation findings. Exact-SHA execution status is
authoritative only in Core OS CI artifacts and the annotated qualification tag.

| Area | Severity | Implementation result | Release gate |
|---|---:|---|---|
| Evidence identity | P0 | stable Architecture Contract, deterministic semantic tree identity, volatile SHA-bound artifacts | final release artifact must contain all eight required evidence classes |
| Validation authority | P0 | `migration.item.validate` computes and persists server-side validation; approval accepts only its id | stale/revoked/mismatched validation must reject |
| Migration semantics | P0 | archival state, domain state, validation scope and run completion are distinct | `DOMAIN_NATIVE` cannot pass with pending review or failures |
| Core domain adapters | P0 | exactly 18 source types have real Authority adapters; remaining 41 stay archival | all 18 must pass PostgreSQL integration on final SHA |
| Story Design validation | P0 | versioned schema, structural, semantic, generator-contract and planning-scope validators | no caller-supplied `passed=true` path |
| Structured references | P0 | typed relation, optionality, type/hash/cardinality/scope checks and dependency graph | ambiguity, cross-project, mismatch and cycle fail closed |
| Runtime Job plane | P0 | Book and Maintenance use fenced, resumable non-business Runtime Jobs | Runtime Job never owns business state |
| Outbox execution | P0 | dedicated delivery authority retains Outbox ownership while exposing equivalent lease/fence/checkpoint guarantees | stale claim and poison recovery required |
| Worker Fleet | P0 | seven independent Compose scenarios and fail-closed fleet summary implemented | all seven exact-SHA matrix jobs must pass |
| Worker governance | P1 | derived database status, safe pool identity and cross-process metrics projection | no full DSN in registry metrics or logs |
| Remote qualification | P0 | workflow emits test, migration, coverage, Compose, query, fleet, Docker and environment artifacts | final Required Jobs green, then annotated tag on same SHA |

No item in this table upgrades fixture evidence to real-provider, production,
long-form, multi-book, backup/PITR or autonomous Book Loop proof.
