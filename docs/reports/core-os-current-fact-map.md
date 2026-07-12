# Core OS Current Fact Map

Date: 2026-07-12. This map records current-code observations, not completion claims.

| Surface | Entry/state authority | Persistence | Model/side effect | Bypass/failure boundary |
| --- | --- | --- | --- | --- |
| Production Kernel | `dispatch_production_operation`; `ProductionOperation` parent projection | LocalStorage `data/runs` | routes selected chapter/workflow/agent/loop operations | registry is partial; lifecycle is bounded and LocalStorage-backed |
| Chapter Bus | `ChapterProductionRun` child state | LocalStorage | draft/review/revision/recap/export | sequence now dispatches through Kernel; several legacy controls remain |
| Workflow/Agent/Loop | distinct child-run states | LocalStorage | workflow processors, scheduler, loop runners | direct compatibility/control paths remain |
| Model runtime | Model Gateway / GuardedModelAdapter / Codex CLI adapter | Local ModelCallLog assets | Codex subprocess with JSON schema | nested context can reach prompt; no universal immutable manifest |
| PostgreSQL | runtime Schema is in the formal migration chain and verified on isolated PostgreSQL; `PostgresAssetStore` remains asset sync | `nf_assets`, MKAOS, and Core OS runtime tables | asset synchronization only | Repository, UoW, production wiring, and concurrency semantics are not yet implemented |
| State bus | Local `StateEvent` and Outbox assets | LocalStorage | local claim/ack | no transaction or SKIP LOCKED claim |
| Review/Revision | ReviewReport/RevisionPlan assets | LocalStorage | model-backed or deterministic review | no universal completion gate or revision-gain authority |
| Longform | Canon/recap and state assets | LocalStorage | reducer/report generation | no append-only PostgreSQL StoryStateEvent authority |

Static evidence: `rg` identifies direct runner calls outside the limited registry
and numerous `LocalStorage` entrypoints. Runtime evidence: the isolated real
Codex run under `.local/phase01-real10-audit` generated a parent Operation and
ModelCallLogs but failed before a valid chapter because its prompt exceeded the
Codex limit. Database evidence: current migrations create asset/MKAOS tables,
not operation/event/outbox tables.
