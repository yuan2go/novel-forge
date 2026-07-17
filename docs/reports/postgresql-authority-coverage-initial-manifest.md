# PostgreSQL Authority Coverage Baseline

Generated: 2026-07-18 Asia/Shanghai

This Markdown summary describes the machine-generated artifacts at the current
Command Kernel source snapshot. The JSON files remain authoritative.

## Snapshot binding

- Source commit: `1ef93fa8a540826c542a80ad44a2a3f1bd9a8ce8`
- Source tree SHA: `c347ac8cd31e7d7f063ec01f807b9df97cb23c71`
- Binding: latest commit affecting `src/novel_forge` plus the exact working-tree source hash
- Generator: `2.1.0`
- Scan rule: `receiver-aware-v2`

This binding deliberately does not require the generated JSON to contain the
hash of the later docs-only commit that stores the JSON. That would be a
self-reference. Any committed or uncommitted change under `src/novel_forge`
still changes the binding and fails the architecture check.

## Current inventory

| Measure | Current value |
|---|---:|
| Python files scanned | 465 |
| Files with findings | 202 |
| Receiver-aware findings / legacy actions | 2,131 |
| Owner symbols | 1,456 |
| Authority writes | 380 |
| Authority reads | 1,642 |
| External effects | 43 |
| Fallback paths | 46 |
| Sync paths | 13 |
| Export paths | 3 |
| Unknown classifications | 4 |
| Mapped side effects | 486 |
| Unmapped side effects | 0 |

## OperationDefinition catalog

The current catalog contains **114** definitions across core and content-domain families:

- **17** definitions are mapped to current entrypoints but have no bound handler;
- **22** content-intelligence definitions have concrete storage-free handlers
  and remain disabled at `handler_bound` pending PostgreSQL integration proof;
- **10** PostgreSQL-only `chapter_authority` definitions are
  `integration_proven` by the committed PostgreSQL test contracts;
- **65** remain unbound migration candidates;
- the `asset`, `blob`, `external_effect`, and `chapter_authority` families are included.

The previous `63 definitions / 17 mapped / 46 candidate` statement is stale
and must not be used as current evidence.

## Machine-readable authority

- `docs/reports/postgresql-authority-coverage-baseline.json`
- `docs/reports/postgresql-operation-definition-catalog.json`
- `docs/reports/postgresql-authority-legacy-actions.json`

The coverage manifest reports no unmapped side effects. This means the static
inventory has an assigned migration action and target definition; it does not
mean all 93 definitions are enabled or that LocalStorage is no longer a
production authority. Runtime maturity now separately records `candidate`,
`mapped`, `handler_bound`, `enabled`, `integration_proven`, and
`production_verified`; real-provider and long-form proof remain independent
evidence flags.
