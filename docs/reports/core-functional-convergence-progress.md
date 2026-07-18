# Core Functional Convergence Progress

Updated: 2026-07-18. Evidence source commit: `ed30ab6` (generated authority artifacts are committed separately).

## Result

The PostgreSQL-only chapter slice now runs Plan → governed Context → Draft → ReviewIssue → Revision → independent Re-review → Canon Extraction → stateful Canon Reduction with independent snapshots → evidence-aggregated Quality → Publish Gate → verified Export → Post-Blob Final Release Gate. All 22 content-intelligence definitions execute through the shared fenced PostgreSQL runtime and its recovery-aware Attempt scheduler. The deterministic provider remains explicitly a fixture.

| Slice | Status | Code | Tests | Commit |
|---|---|---|---|---|
| Baseline recovery | integration_proven | `workers/tasks.py`, schema/test extras | worker/schema focused suite | `bfd7d90` |
| Definition maturity | implemented | `chapter_authority/definitions.py`, coverage generator | definition/architecture tests | `2c5b1dd` |
| Governed Context | integration_proven in chapter chain | manifest/segment/stage view + frozen inputs | context isolation + PostgreSQL Saga | `1f7154f` |
| Review/Revision/Re-review | integration_proven | issue claim/verification/delta domains | unit + PostgreSQL Saga | `1f7154f` |
| Canon Extraction/Reduction | integration_proven | independent extraction + typed historical conflicts | stateful Canon unit + PostgreSQL Saga | `70c2434` |
| Canon Snapshot materialization | integration_proven | CanonPatch + nine append-only AssetVersions in one fenced transaction | Completion selectors + PostgreSQL Saga | `d9d0154` |
| Quality/Publish | integration_proven; uncalibrated | evidence dimensions + checklist/approval refs | unit + PostgreSQL Saga | `1f7154f` |
| MKAOS/Source/Connectors | implemented | selection/eligibility/connector domains | 50 focused source/context tests | `9d49479`, `759ada0`, `bae6f10` |
| 22 Content operations | integration_proven | explicit codecs + shared fenced runtime | all-definition PostgreSQL fixture | `9418d73`, `d442767`, `c698a36` |
| Chapter Bus convergence | implemented | Authority adapter + rebuildable projection + production guard | adapter/envelope tests | `9895b70` |
| Post-Blob Final Release | integration_proven | independent final gate consumes verified Blob/effect/receipt evidence | domain + PostgreSQL Saga | `d9d0154` |
| Content scheduler recovery | integration_proven | retry, lease takeover, replay, stale fencing, audit/outbox uniqueness | PostgreSQL fault fixtures | `a38edc7` |

Real-provider proof and long-form proof were not run; this round is functional convergence only. Legacy LocalStorage services remain compatibility entrypoints and are not claimed migrated unless listed in the PostgreSQL matrix.
