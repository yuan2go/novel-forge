# Development Gap Final Convergence Qualification

## Authority baseline

- Starting Git SHA: `aa6734799c693f1d669a5b3781d69ef5d888e15f`
- Baseline: exact `origin/main` after fetch
- Baseline migration head: `20260812_0084_development_gap_final_convergence`
- Final migration head: `20260812_0085_corrective_action_terminal_lineage`
- Production architecture: PostgreSQL Authority, Command Kernel, Operation/Attempt/Lease/Fence, ExternalEffect, Production Execution Gateway, existing Chapter and Book runtimes

Migration 0084 already owns the non-derivable Book replan re-evaluation fact
and the derived Corrective Action/MKAOS projections. Final code review found
that the 0084 Quality projection only joined successful correction Operations.
Forward-only migration 0085 renames that projection to an explicit
`MIGRATION_ONLY` base and wraps it with terminal Operation/Attempt and action
AssetVersion lifecycle derivation. No history was edited and no new table or
execution Authority was added.

The production Compose smoke also found a baseline entrypoint defect outside
the four domain gaps: Compose invoked `python -m novel_forge.cli.authority`, but
the module did not call `main()` when executed as a module. The API therefore
exited successfully and restarted forever. The canonical CLI module now has a
single `SystemExit(main())` entrypoint guard, protected by an architecture test;
no alternate CLI or service path was added.

## Baseline reassessment

| Gap | State on starting SHA | Remaining defect found |
|---|---|---|
| Source analysis methodology identity | `FIXTURE_PROVEN` | The complete strategy fingerprint and admission-frozen strategy were already wired. The test matrix did not enumerate every analyzer/capability/provider/aggregation field explicitly. |
| Narrative proof data plumbing | `WIRED` | Planning, MKAOS, and Provider inputs were present, but temporal/obligation/knowledge/Quality metrics could still report false zero. Receipt and trace availability were not independently stated. |
| Corrective Action lifecycle | `WIRED` | Review correction and Book replan re-evaluation existed, but aggregate Quality required actions were only projected. No Chapter Operation actually consumed a Quality `revision_task` and ran bounded Quality re-evaluation. |
| MKAOS runtime consumption lineage | `FIXTURE_PROVEN` | Selection and exact Provider consumption were already separated and queryable. Qualification and measurement availability needed confirmation, not a second receipt model. |

## Converged runtime

### Source invalidation and reuse

The one canonical identity remains `ResolvedAnalysisStrategy.fingerprint`. It
freezes content type, profile, routing, analyzer/prompt/schema, Skill
id/version/SKILL.md digest, Capability, provider/aggregation policy, scales,
window limits, MKAOS Capability, and abstraction policy.

| Change | Source | Normalize/Chunk | Profile | Plan/Task/Observation/MKAOS |
|---|---|---|---|---|
| Nothing | reuse | reuse | reuse | reuse |
| SKILL.md bytes | reuse | reuse | reuse | reanalyze affected strategy |
| Skill version | reuse | reuse | reuse | reanalyze affected strategy |
| Profile/analyzer/routing/capability/provider/aggregation | reuse | reuse | reuse unless classifier contract changed | reanalyze affected strategy |
| Classifier contract | reuse | reuse | reprofile | replan and reanalyze |
| Source content | new Source lineage | renormalize/rechunk | reprofile | replan and reanalyze |

### Narrative Measurement

`NarrativeRuntimeMeasurement v2` consumes the frozen Context Manifest and
segments, Temporal Narrative State facts, ChapterPlan constraint envelope,
aggregate Quality actions, exact-context model-call/cost evidence, Provider
effect ids, usage/cost receipt refs, trace ids, retries, and MKAOS usage
lineage. Metrics are nullable when their evidence is absent. Observation states
are `MEASURED`, `NOT_OBSERVED`, `NOT_AVAILABLE`, or `NOT_APPLICABLE`. Provider
token and cost totals are nullable and have independent availability states;
the runtime no longer manufactures zero when usage or cost fields are absent.
Planning drift is measured only when the frozen plan contains an actual
constraint envelope.

Observed empty Authority evidence produces a measured zero. Missing or
unverifiable evidence produces `null` plus its availability state. The context
distance metric is named `long_distance_context_selected_count`; recall is only
reported when an expected relevant set exists.

### Corrective Action

The Chapter scheduler now admits one bounded correction generation with the
existing Chapter Operation definitions:

```text
Quality required_action AssetVersion
  -> Revision Operation consumes frozen task + target revision + Context
  -> corrected Draft AssetVersion
  -> existing Canon extraction/proposal/update Operations
  -> existing five Quality group Operations
  -> aggregate Quality re-evaluation
  -> CorrectiveActionQuery: RESOLVED or ESCALATED
```

The correction uses the existing root Operation, Attempt/Lease/Fence,
ExternalEffect behavior when the configured Provider is remote, immutable
outputs, deterministic exact idempotency keys, and the existing retry/cancel
terminal states. It is not a second workflow or retry plane. Re-evaluation does
not emit a recursive new task; an unresolved action is escalated after the
bounded correction. Execution failure/cancellation and superseded action
versions project as `FAILED`, `CANCELLED`, and `SUPERSEDED` rather than remaining
`ADMITTED`.

The existing longform path remains:

```text
Longform Recap deviation
  -> governed Replan
  -> PlanChange decision and activation
  -> future Chapter production only
  -> later Recap re-evaluation
  -> RESOLVED or ESCALATED/FAILED
```

Reader evidence remains a future-only adjustment proposal and cannot mutate an
accepted chapter, accepted Canon, or executed plan history.

### MKAOS lineage

```text
Approved Knowledge Card
  -> immutable Knowledge Pack selection in Context Manifest
  -> exact ContextBundle input to a successful Provider ExternalEffect
  -> Operation + Attempt + Capability Pack snapshot
  -> generated/reviewed/revised result AssetVersion
  -> authority_mkaos_runtime_usage_projection
```

`MkaosAuthorityQuery` supports project/Book/position, Knowledge Card, Context,
Capability, Operation/Attempt, Provider effect, Capability Pack snapshot, and
result queries. A selected Pack with no Provider execution has selection rows
and zero consumption rows. Retry/replay is a distinct projection over immutable
effect/result identity and cannot create a duplicate logical consumption row.

## Capability Proof Matrix

| Capability | Proof state | Evidence ceiling |
|---|---|---|
| Source methodology invalidation/reuse | `FIXTURE_PROVEN` | Unit field matrix plus PostgreSQL Source Import reuse/reanalysis matrix |
| Narrative Measurement evidence plumbing | `FIXTURE_PROVEN` | Unit missing/zero/contradiction tests plus mock-gateway PostgreSQL receipts |
| Quality issue correction and re-evaluation | `FIXTURE_PROVEN` | PostgreSQL `RESOLVED` and `ESCALATED` paths with replay deduplication |
| Longform Replan/PlanChange/re-evaluation | `FIXTURE_PROVEN` | Two-chapter governed PostgreSQL fixture; not longform proof |
| MKAOS selection versus consumption lineage | `FIXTURE_PROVEN` | Selected-only and exact-context Provider execution PostgreSQL tests |
| Real-provider narrative correctness | `MISSING` | No real-provider run in this task |
| 30-chapter narrative correctness | `MISSING` | Explicitly out of scope for this convergence task |
| Multi-book correctness | `MISSING` | Explicitly out of scope |
| Production authorization/SLO history | `MISSING` | No deployment or operational authorization evidence |

## Engineering qualification

| Command | Result |
|---|---|
| Focused Source Intelligence unit + PostgreSQL matrix | 25 unit passed; 5 PostgreSQL passed |
| Focused Chapter/Measurement/MKAOS PostgreSQL group | 16 passed before final full gate |
| `tests/integration/test_authority_migrations_postgres.py` | 3 passed: fresh chain, historical upgrade, 0084 to 0085 upgrade |
| `make validate` | PASS: compile, Ruff, 85 migrations, manifests, architecture fitness, Compose |
| `make authority-test` | 936 passed |
| `make authority-postgres-test` | 182 passed, 60 subtests passed |
| Capability Pack unit validation | 183 passed, 1308 subtests passed |
| `make sync-skills-dry-run && make check-skills` | PASS, no drift |
| Admin `test`, `lint`, `build` | 11 tests passed, TypeScript passed, 74 routes built |
| `uv build` to a temporary output directory | sdist and wheel built |
| `make authority-build` | 11 production-composition images built |
| `scripts/verify_authority_compose.py` | PASS: 9-worker readiness/drain, worker restart recovery, lease takeover, stale-fence rejection |
| `make authority-query-plan-release` | PASS at six representative 10k/100k-row query surfaces |

Python has no configured mypy/pyright gate. Python compile/Ruff and the typed
runtime tests are reported as such; the TypeScript project has a real `tsc
--noEmit` gate.

## Recovery and duplicate prevention

- Corrective correction replay reuses the same idempotency keys and creates one
  Revision and one aggregate re-evaluation per bounded generation.
- Command admission concurrency, Attempt retry/dead-letter, lease takeover,
  stale-fence rejection, cancellation, ExternalEffect reconciliation, and
  receipt replay passed the non-skippable PostgreSQL gate.
- Source methodology changes preserve upstream content identities and replace
  only affected downstream lineage.
- MKAOS usage is derived from unique ExternalEffect, Knowledge Card, and result
  identities; repeated queries/replay return the same logical rows.
- Book Replan re-evaluation uses a deterministic command key; response replay
  returns the same re-evaluation identity.

## AI overengineering review

The final diff adds no Agent, Judge, persona, Provider, Workflow Engine,
Authority plane, retry runtime, proof framework, DTO family, registry, adapter,
manager, receipt, or schema table. Quality correction is deliberately one
bounded generation over existing Chapter Operations and immutable assets. MKAOS
consumption remains a derived Authority projection instead of a copied lineage
record, and Source analysis retains its single canonical strategy fingerprint.
The one forward migration only repairs derived terminal-state projection
semantics and marks its replaced base view `MIGRATION_ONLY`.

The obsolete behavior removed is semantic rather than architectural: aggregate
Quality tasks are no longer passive projection-only records, missing narrative
evidence is no longer converted to zero, and the Compose module entrypoint no
longer exits without starting the service. No replaced production path or
migration-only compatibility path remains in this diff.

## Remaining gaps

- `DEVELOPMENT_GAP`: none identified by the final local engineering gates.
- `PROOF_GAP`: real-provider, 30-chapter, longform, multibook, and production
  narrative correctness are not proven.
- `OPERATIONS_GAP`: deployment authorization, CI-provider evidence, SLOs,
  alerts, and sustained production history are not part of this local task.
- `OPTIONAL_FUTURE_WORK`: run the separately authorized 30-chapter narrative
  correctness proof without adding a new execution or proof framework.

`DEVELOPMENT_GAP_FINAL_CONVERGENCE_COMPLETE = true`

`BLOCKING_ENGINEERING_GAPS = []`

`NEXT_PHASE = 30_CHAPTER_NARRATIVE_CORRECTNESS_PROOF`
