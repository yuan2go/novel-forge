# V7 Content Intelligence And Longform Proof - Current Analysis

Updated: 2026-07-05
Branch: `feat/v7-content-intelligence-and-longform-proof`

This document analyzes the current v7 branch against the target: **Novel Operating System that can produce high-quality long-form novels across genres, platforms, and styles**.

The analysis is based on current code and current docs, not historical claims. Older documents remain useful as design references only when confirmed by code, tests, or current documentation.

---

## 1. Executive Conclusion

The v7 branch has advanced beyond the earlier v6 runtime slice. It now has the beginnings of the OS substrate: ModelRouter/ModelGateway, PromptRegistry, ToolGateway, StateBus, AgentMessageBus, L0-L5 memory, pgvector/hybrid retrieval, Canon Graph, Context Builder integration, provider runtime governance, and workflow/agent operation contracts.

However, the branch is still not a complete **content-intelligence layer** for industrial long-form fiction production.

Current state:

```text
Novel OS runtime foundation: strong and increasingly complete.
Content-intelligence product layer: partial.
Long-form proof: partial; needs stronger 50/100/300 chapter acceptance.
Genre/style/productized quality control: still the main gap.
```

The next development cycle should not create a parallel writing pipeline. It should add a **Content Intelligence Layer** on top of existing Context Builder, MKAOS, Canon Graph, Agent Scheduler, Loop Kernel, Evaluation Center, and publishing gates.

---

## 2. Evidence Summary

### 2.1 Runtime foundation exists

The README defines Novel Forge as a local-first AI novel production platform and early Novel Operating System runtime. It explicitly states that the acceptance chain proves workflow, agent dispatch, KG gates, trace, cost, review rework, invalidation, and resume, but is not the same thing as complete long-novel generation.

Key runtime components already described in the branch:

- Workflow / Agent Scheduler.
- Context Bundle.
- Runtime model-call boundary.
- TraceSpan / GateResult / ModelCallLog / CostLedger.
- Novel KG gate / continuity preflight.
- ReviewIssue -> RevisionTask -> EditorPatch -> DraftVersion.
- Re-review and publish gate.
- Invalidation / resume.
- Cost-quality dashboard and acceptance report.

### 2.2 Current state documents mark many systems as partial

`docs/project-current-state.md` records these capabilities as partial or not fully productized:

- MKAOS: broad coverage, but graph depth and production learning loop are partial.
- Long-form stability: partial; full novel-scale autonomous stability is not proven.
- Canon: partial; human-grade conflict resolution and merge workflows are partial.
- Context Builder: partial; manual controls, KG-backed context, and invalidation warnings need depth.
- Agent Center: partial; operation coverage and production UI depth remain partial.
- Quality gate / Eval Center: partial; unified gate semantics still being hardened.
- Publishing/platform operations: partial; external platform integration and production coverage need depth.

This confirms that v7 should focus on **product depth** rather than only adding more runtime infrastructure.

### 2.3 Current roadmap still prioritizes runtime correctness

The current roadmap places P0 on:

- Universal provider/runtime evidence.
- Publish/release gate completeness.
- Agent operation coverage.
- Context/KG/Canon consistency.
- Environment policy for local vs production.

P2 then targets:

- Productized Eval Center.
- Stronger long-form continuity.
- Reader feedback backflow.
- Publishing/platform operations.

This means the next phase must bridge P0 runtime correctness and P2 content-quality proof.

### 2.4 V7 OS capabilities are implemented as first production slices

`docs/architecture/novel-operating-system-new-capabilities.md` records implementation of:

- ModelRouter / ModelGateway.
- PromptRegistry / PromptOps.
- Tool Gateway / MCP registry.
- StateBus.
- AgentMessageBus.
- L0-L5 Long Memory.
- pgvector schema plan / local projection / HybridRetriever.

The same doc records API entries under `/product/os/*`, workflow processor operations, AgentOperationRegistry operations, Context Builder backend support for `auto/local/qdrant/pgvector/hybrid`, and a pgvector-first fallback policy.

### 2.5 Genre/topic is still too thin for multi-genre production

`src/novel_forge/modules/topics/service.py` exists, but `develop_topic()` currently calls a generic prompt: `Develop a differentiated suspense topic seed.` The deterministic writer stores a fixed suspense topic such as `钟楼回声调查`, with hard-coded suspense positioning.

This is useful as a working slice, but it is not a real Genre OS. It cannot yet represent:

- Genre taxonomy.
- Subgenre mechanics.
- Platform x genre matrix.
- Genre-specific long-form risks.
- Genre-specific worldbuilding/persona/beat/pacing templates.
- Genre-specific acceptance gates.

### 2.6 Canon Graph exists, but needs domain-specific reasoning depth

`src/novel_forge/modules/canon_graph/service.py` exists and includes:

- `build_canon_graph()`.
- `reason_canon_graph()`.
- `query_canon_graph_paths()`.
- `query_canon_graph()`.
- `check_canon_graph_conflicts()`.
- `persist_canon_graph_issues()`.
- `diff_canon_graph()`.

It has asset types such as canon database, character card, character state ledger, arc plan, foreshadowing graph, world bible, continuity bible, power scale rule, and fact ledger.

It also has reasoning relations such as identity, alias, forbidden alias, arc participation, payoff requirement, foreshadowing, constraint, and forbidden term.

This is strong enough for a Canon Graph first slice, but not yet enough for all genre-specific semantic reasoning. It still needs specialized engines for:

- Power scale and cultivation progression.
- Mystery evidence chain and timeline logic.
- Romance relationship state and emotional reversals.
- Historical/political faction logic.
- Sci-fi rule consistency.
- Horror/strange-rule contamination logic.

### 2.7 Eval Center has broad dimensions but scoring is still heuristic

`src/novel_forge/modules/evaluation_center/service.py` defines useful dimensions:

- Content quality: readability, hook strength, emotional curve, conflict density, plot progress, character motivation, scene vividness, dialogue quality, AI flavor risk, originality risk.
- Long-form: canon consistency, character drift, arc progress, foreshadowing tracking, power scale consistency, timeline consistency, world rule consistency.
- Engineering: schema validity, context adherence, source isolation, OS envelope coverage, trace coverage, cost, latency, failure rate, rollback readiness.
- Platform: opening gate, chapter rhythm, retention risk, publish compliance, feedback backflow quality.

But `_score_asset()` is still mostly string/length heuristics: hook strength checks whether words like hook/钩子/悬念 appear; conflict density checks terms like 冲突/风险/阻碍/代价; several long-form dimensions are fixed values. This is acceptable for runtime smoke tests, not for judging精品长篇.

---

## 3. Gap Map

| Area | Current State | Gap | Required Direction |
|---|---|---|---|
| Genre OS | Basic topic generation and platform strategy exist | No independent genre taxonomy/strategy/gate layer | Add genre taxonomy, subgenre mechanics, genre strategy packs, platform x genre matrix |
| Style OS | StyleControlPlan exists inside longform stability slice | No style sample ingestion, fingerprint, profile, drift gate, rewrite policy | Add style fingerprint engine and style gate |
| Canon Graph | Existing graph and basic reasoning | Needs genre-specific semantic engines and stronger conflict lifecycle | Add power/timeline/evidence/relationship/world-rule engines |
| Quality Eval | Broad metric names exist | Scoring remains heuristic and not calibrated | Add rubric packs, model/human judges, regression cases, genre/platform quality suites |
| Long-chain proof | README mentions 12/50 pressure acceptance; code docs show partial long-form proof | Need reliable 50/100/300 chapter acceptance artifacts and slow tests | Add staged deterministic, mock, and provider-gated long-chain suites |
| Publishing | Release package and platform strategy exist | Real adapters/receipts/status workflow partial | Add manual/real platform adapter contract, receipt schema, upload package, status tracking |
| Feedback | Feedback import, simulation, sentiment and backflow exist | Real reader cohort analytics and governed plan mutation partial | Add platform metric normalizer, comment clustering, dropoff detector, plan mutation proposals |
| Agent coverage | AgentScheduler exists and OS operations registered | Full production role coverage incomplete | Register content-intelligence operations and gate them through Loop/Agent/Context/MKAOS |
| UI | Many routes exist | Some are consoles/reports, not executable product workflows | Add Genre/Style/Quality/Long-chain Proof consoles with forms and action flow |

---

## 4. Content Intelligence Target Layer

The missing product layer should be called:

```text
Content Intelligence Layer
```

It should contain:

```text
Genre OS
Style OS
Canon Graph 2.0
Quality Eval 2.0
Long-chain Proof Center
Publishing/Feedback Adapter 2.0
Agent Operation Full Coverage
```

This layer must integrate with existing OS primitives:

```text
Content Intelligence Layer
  -> Context Builder
  -> MKAOS Production Gate
  -> Canon Graph / Novel KG
  -> Long Memory L0-L5
  -> Agent Scheduler
  -> Loop Kernel
  -> Evaluation Gate
  -> Publish Gate
  -> Feedback Backflow
  -> Trace / Cost / Runtime Ledger
```

No new module may bypass these primitives.

---

## 5. Prioritized Development Recommendations

### P0 - Content Intelligence Foundation

1. **Genre OS**
   - Add `genre_profile`, `genre_strategy_pack`, `subgenre_mechanic`, `genre_risk_gate`, `platform_genre_fit`.
   - Add API and UI to create and inspect genre strategy packs.
   - Wire Genre OS into topic/world/character/outline/chapter-plan/prose Context Builder flows.

2. **Style OS**
   - Add style sample ingestion, style fingerprint, style profile, style generation policy, style drift report, style rewrite task.
   - Wire Style OS into draft, review, revision, and Eval Center.

3. **Canon Graph 2.0**
   - Extend existing Canon Graph with typed reasoning engines.
   - Add genre plugins: fantasy power scale, mystery evidence chain, romance relationship state, historical faction network, sci-fi rule system.

4. **Quality Eval 2.0**
   - Add rubric packs and evaluation suites for opening 3 chapters, golden 10 chapters, 30-chapter volume, and 100-chapter long-chain acceptance.
   - Use local heuristics as fallback only; support model/human judge calibration.

### P1 - Production Loop Depth

5. **Long-chain Proof Center**
   - Add deterministic 50-chapter pressure suite.
   - Add mock 100-chapter continuity suite.
   - Add optional provider 30-chapter slow suite.
   - Add dashboard-ready acceptance report.

6. **Publishing/Feedback Adapter 2.0**
   - Add platform upload package, receipt schema, status tracking, comment/metric import, and governed feedback-to-plan mutation.

7. **Agent Operation Full Coverage**
   - Register all new content-intelligence operations in AgentOperationRegistry.
   - Add LoopRun evidence for genre/style/quality/proof operations.

### P2 - UI and Operator Depth

8. Add product workflows for:
   - Genre Console.
   - Style Console.
   - Canon Graph Workbench 2.0.
   - Quality Eval Console.
   - Long-chain Proof Console.
   - Publishing Feedback Console 2.0.

---

## 6. Acceptance Definition For V7 Completion

V7 should be considered complete only when the following are true:

1. A project can create genre + platform + style strategy packs before outline generation.
2. Context Builder includes genre/style/Canon/Long Memory evidence for outline, chapter plan, prose, review, revision, recap, publish, and feedback flows.
3. Draft generation cannot bypass Genre OS, Style OS, Canon Graph, MKAOS Production Gate, provider runtime policy, and Evaluation Gate in production/OS mode.
4. At least one deterministic 50-chapter and one mock 100-chapter suite produce auditable long-chain acceptance reports.
5. Quality Eval can score opening 3 chapters, golden 10 chapters, volume 30 chapters, and longform 100 chapters using rubric packs.
6. Reader feedback can produce traceable, human-gated plan/revision/style/genre adjustments.
7. Publishing package has platform-specific payload and receipt schema.
8. Agent Center can show operation coverage for all content-intelligence operations.
9. UI can execute, not only inspect, core Genre/Style/Quality/Long-chain Proof workflows.

---

## 7. Recommended New Documents

This analysis should be read with:

1. `docs/new/v7-content-intelligence-product-spec.md`
2. `docs/new/v7-content-intelligence-architecture.md`
3. `docs/new/v7-claude-code-next-development-prompt.md`

These documents convert the gap analysis into PRD, architecture, implementation sequence, and Claude Code execution prompt.
