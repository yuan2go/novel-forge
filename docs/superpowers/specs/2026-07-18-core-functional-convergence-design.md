# Novel OS Core Functional Convergence Design

## Scope

This design converges five bounded areas only: PostgreSQL Command Kernel business migration; Context Builder/MKAOS/Source Governance; Creative/Worldbuilding/Character; Meaning/Theme/Ending; and long-form semantic stability. It does not add Portfolio dispatch, real platform publishing, multi-book production, or long-provider acceptance.

## Design decision

The implementation uses one rule source per domain:

```text
storage-free domain core
  -> typed input/output port
  -> PostgreSQL Authority handler
  -> AssetVersion + qualification + completion evidence
  -> optional LocalStorage compatibility adapter
```

LocalStorage services may call the domain core during migration. Authority handlers never call LocalStorage and never use a projection to satisfy Completion. Mock/deterministic behavior is labelled fixture evidence and cannot advance `real_provider_proven` or `longform_proven`.

## Operation maturity contract

Every catalog entry exposes both compatibility `migration_status` and the canonical `definition_status`:

```text
candidate -> mapped -> handler_bound -> enabled -> integration_proven -> production_verified
```

Evidence dimensions remain independent:

```text
documented
implemented
handler_bound
integration_proven
real_provider_proven
longform_proven
```

`enabled` requires a concrete handler and frozen input/output/completion contracts. `integration_proven` requires a PostgreSQL test. `production_verified` requires non-fixture provider evidence where the operation uses a model.

## Internal migration matrix

| Capability | Existing capability | Current authority | Duplicate today | Domain core to reuse/extract | Target definition | Input AssetVersions | Output AssetVersions | ExternalEffect | Completion | Projection | Priority |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Context | Stage profiles, isolation, MKAOS pack, budget | LocalStorage | yes: simplified chapter handler | Context selection/profile/isolation core | `context.build` | plan, outline, world, character, canon, knowledge, source policy | context bundle | none | immutable bundle, eligibility, digest, audit/outbox | ChapterProductionRun context row | P0 |
| Review | Review reports and structured issues | LocalStorage | yes | review normalization and issue gate core | `review.run`, `review.resolve_issue` | draft, context, rubric | review report, review issues | model effect only for provider review | issue evidence, latest qualification | review display model | P0 |
| Revision | Revision plan/editor patch/version lineage | LocalStorage | yes | revision strategy and resolution core | `revision.apply` | draft, review issues, context | draft version, issue resolutions | model effect only for provider revision | all blocking issues resolved | chapter run revision row | P0 |
| Canon | Canon graph, reducer, conflict issues | LocalStorage | yes | canon candidate/conflict/impact core | `canon.update`, state/foreshadow/recap definitions | accepted canon, draft version, context | canon patch/snapshot/diff | none | no blocking conflict, version lineage | canon console | P0 |
| Quality/publish | Quality loop, publish gate, release package | LocalStorage | yes | quality and release eligibility core | `quality.evaluate`, `quality.run_completion_gate`, `publishing.prepare_release` | final draft, canon, review issues, source/originality evidence | quality report, publish gate, release package | object-store effect at export only | latest effective evidence and verified blob | dashboards/release view | P0 |
| Creative | topic and genre foundations | LocalStorage | incomplete | candidate generation/evaluation/fingerprint core | `creative.*` family | creative brief, genre/style/knowledge | candidates, novelty report, proposal | optional model effect later | differentiated candidates and gate | creative comparison | P1 |
| World | deterministic derived WorldBible | LocalStorage | no reusable deep core | goal-driven world rule core | `world.generate`, `world.validate` | approved proposal, creative brief | world bible, conflict report | optional model effect later | rules have scope/cost/consequence | world console | P1 |
| Character | deterministic derived CharacterCard | LocalStorage | no reusable deep core | character/relationship core | `character.generate`, relationships/validate | brief, world, theme | character cards, relationships, validation | optional model effect later | agency, cost, arc, relationships | character console | P1 |
| Theme/ending | blueprint concepts only | none | no | new deterministic domain cores | `theme.*`, `ending.*` | brief, character/world/arc/promise/foreshadow | theme arc, anti-preaching report, closure plan, ending gate | none in this round | evidence-backed choices/payoffs | editor/recap views | P1 |
| Long-form semantics | canon/recap heuristics | LocalStorage | fragmented | semantic report core | `longform.*` | accepted snapshots and current chapter evidence | drift/merge/payoff/conflict/debt reports | none | issue/gate on high-impact findings | recap/canon views | P1 |

## Context authority

The authoritative ContextBundle is immutable and freezes project/stage/profile, all selected and rejected AssetVersion ids, relevant policy/snapshot versions, token budget, actual digest, isolation result, invalidation keys, and creating Operation id. Draft, review, revision, canon extraction, quality, recap, and ending consume a specific bundle version. Production handlers cannot scan the workspace.

MKAOS selection is explainable: governance eligibility runs before scoring; scoring combines relevance, stage/genre/narrative fit, trust/risk, quality, freshness, history, redundancy, conflict, and project specificity. Rejected items retain reason codes. Revoked/stale/quarantined or cross-project inputs fail closed.

## Creative, world, character

Creative candidates are mechanisms, not renamed premises. Fingerprints cover protagonist advantage, conflict/growth/reward loops, information asymmetry, world constraints, relationship engine, antagonist response, and payoff pattern. Clustering and novelty gates select a reviewable ProjectProposal.

World rules include scope, cost, exception, consequence, narrative function, conflict potential, failure mode, and canon policy. Character profiles include desire/need/fear/wound/belief/value/moral boundary/capability/cost/agency/voice/identity/secret/relationships/arcs. Relationship edges are versioned state, not static prose.

## Meaning and ending

Theme questions must be actionable dilemmas. Value conflicts evolve through position, pressure, choice, cost, consequence, and belief change. Anti-preaching findings carry evidence locators and revision strategy. Closure uses one payoff matrix spanning promises, foreshadowing, mysteries, relationships, arcs, world rules, rewards, theme, and antagonist threats; unresolved or breached obligations cannot be deleted to pass.

## Long-form semantics

The semantic core produces motivation drift, identity merge proposals, foreshadow payoff quality, world-rule conflict, power conflict, narrative pattern repetition, arc progress, and narrative debt. Each report is project-scoped, version-aware, evidence-backed, and can emit ReviewIssue/next-window constraints. Recap reads these reports and writes advisory production policy; it never rewrites accepted prose.

## Failure and testing

Cross-project references, revoked/stale qualifications, stale expected versions, idempotency conflicts, missing completion evidence, and blocking review/canon/source findings fail closed. Tests are layered: pure domain unit tests, schema contract tests, Authority handler tests, PostgreSQL completion/isolation/replay tests, architecture guards, and deterministic single-chapter fixtures. Real provider and long-form acceptance remain explicitly unrun.

