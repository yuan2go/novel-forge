# PostgreSQL Authority Coverage Baseline

Generated: 2026-07-16 22:43 Asia/Shanghai

This Markdown summary describes the machine-generated artifacts at the current
Command Kernel source snapshot. The JSON files remain authoritative.

## Snapshot binding

- Source commit: `87e68b3a1b01362c0578dca573d4801c5c6c8abc`
- Source tree SHA: `24d1abae066a35de6a01791f50074631b334dfe9`
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
| Python files scanned | 432 |
| Files with findings | 201 |
| Receiver-aware findings / legacy actions | 2,127 |
| Owner symbols | 1,454 |
| Authority writes | 380 |
| Authority reads | 1,642 |
| External effects | 39 |
| Fallback paths | 46 |
| Sync paths | 13 |
| Export paths | 3 |
| Unknown classifications | 4 |
| Mapped side effects | 482 |
| Unmapped side effects | 0 |

## OperationDefinition catalog

The current catalog contains **93** definitions across **20** families:

- **17** definitions have mapped current entrypoints;
- **9** PostgreSQL-only `chapter_authority` definitions are implemented;
- **67** remain migration candidates;
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
production authority. Runtime migration status remains separately governed.
