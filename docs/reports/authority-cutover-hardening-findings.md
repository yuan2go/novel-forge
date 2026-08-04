# PostgreSQL Authority Cutover Hardening Findings

Baseline SHA: `a784a52f174cd13c53846eb59a17132a357c2c45`

This report is the human-readable view of
`authority-cutover-hardening-findings.json`. It distinguishes resolved local
implementation from remote final-SHA evidence and deliberately leaves strict
fleet and remaining domain coverage open.

| ID | Severity | Category | Status | Result |
|---|---|---|---|---|
| A | P0 | Migration semantics | FIXED | 18 types are `DOMAIN_NATIVE`; 41 are explicitly `ARCHIVAL_NATIVE`. |
| B | P0 | Domain validation | PARTIAL | Core adapters invoke real Authorities; remaining types are not mislabelled. |
| C | P0 | Reference integrity | FIXED | Two-pass bindings persist Asset, AssetVersion and projection identity. |
| D | P0 | Approval | FIXED | Legacy self-approval is evidence only; independent decisions gate activation. |
| E | P0 | Resume | FIXED | All nine phases persist evidence and advance with expected-version CAS. |
| F | P0 | Reconciliation | PARTIAL | Core domain projections reconcile; archival types have no domain proof. |
| G | P0 | Reachability | FIXED | 15 entrypoints feed a recursive import graph with explicit guard boundaries. |
| H | P0 | Entrypoints/CI | FIXED_LOCAL_REMOTE_PENDING | Local contracts pass; final-SHA GitHub Actions have not run. |
| I | P0 | Worker fleet | OPEN | Only Content has a full Compose operation/restart path. |
| J | P1 | Worker health | FIXED | Health derives from actual attempts, leases and operation outcomes. |
| K | P1 | Transactions | FIXED | Whole-transaction retry is explicit, pure-DB and idempotent only. |
| L | P0 | DB errors | FIXED | Unknown outcome reconciles; protocol violations and signals are not retried. |
| M | P1 | Query plans | FIXED_LOCAL_REMOTE_PENDING | Local representative-scale plans pass; remote release job is pending. |

The unresolved P0 fleet item prevents
`POSTGRESQL_AUTHORITY_BACKEND_RELEASE_QUALIFIED` and
`AUTHORITY_WORKER_FLEET_E2E_PROVEN`. The partial core-domain matrix prevents a
blanket claim that all registered migration types are domain native.
