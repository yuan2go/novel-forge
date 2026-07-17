# Core Functional Convergence Progress

Updated: 2026-07-18. Evidence source commit: `1ef93fa` (generated authority artifacts are committed separately).

## Result

The PostgreSQL-only chapter slice now runs Plan → governed Context → Draft → ReviewIssue → Revision → Canon → Quality → Publish Gate → verified Export. The Context and content-intelligence rules are storage-free domain cores; Authority handlers persist their results as qualified AssetVersions. The deterministic provider remains explicitly a fixture.

| Slice | Status | Code | Tests | Commit |
|---|---|---|---|---|
| Baseline recovery | integration_proven | `workers/tasks.py`, schema/test extras | worker/schema focused suite | `bfd7d90` |
| Definition maturity | implemented | `chapter_authority/definitions.py`, coverage generator | definition/architecture tests | `2c5b1dd` |
| Governed Context | handler_bound; chapter integration_proven | `context_builder/domain.py` | context domain + legacy chain | `8fdb326`, `a897403`, `1ef93fa` |
| Review/Revision/Canon/Quality/Publish | chapter integration_proven | five domain modules + chapter handlers | unit + PostgreSQL slice | `cf5ef1e` |
| MKAOS/Source/Connectors | implemented | selection/eligibility/connector domains | 50 focused source/context tests | `9d49479`, `759ada0`, `bae6f10` |
| Creative/World/Character | handler_bound | content domains and catalog bindings | 7 unit tests | `8179163`, `52a3e39`, `acd0511`, `5aa2a89` |
| Theme/Ending | handler_bound | `theme/domain.py`, `ending/domain.py` | 5 unit tests | `f71b409`, `cb09188`, `5aa2a89` |
| Long-form semantics | handler_bound | `longform_stability/semantic_domain.py` | semantic + recap tests | `235b96a`, `5aa2a89` |

Real-provider proof and long-form proof were not run; this round is functional convergence only. Legacy LocalStorage services remain compatibility entrypoints and are not claimed migrated unless listed in the PostgreSQL matrix.
