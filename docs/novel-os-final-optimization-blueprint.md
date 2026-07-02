# Novel OS Final Optimization Blueprint

Date: 2026-07-02

## 1. 病灶清单

P0:

- 正典漂移：人物、机构、地点、案件名缺少硬锁定。
- 正文污染：JSON、notes、metadata、prompt 泄漏进正文。
- 状态缺失：每章后没有结构化 state，下一章不能稳定继承。
- 结构重复：章节指纹高度相似，长期复用同一调查/压力/钩子链。
- 发布门禁过软：审稿结果不能稳定转化为 block 和 revision_task。

P1:

- 卷级问题弱，扩张多于收束。
- 伏笔没有 target_truth 和 payoff lifecycle。
- 母题预算缺失。
- 人物债务/责任没有结构化账本。
- 反派没有稳定代理人和行动模型。

P2:

- 读者疲劳、动态风格、平台适配、奖励账本、评分体系不够产品化。

## 2. 根因分析

Novel OS 的 writer 能力已经足够单章输出，但 controller/state/reviewer/gate 层没有把“长篇小说”作为一个持续状态机管理。模型每次生成时可以新增名称、机构、线索、旧规和债务，却没有强制付费、回收、降噪和拒绝机制。

## 3. 系统模块拆分

| Layer | Module | Asset |
|---|---|---|
| Canon | Canon Database | `canon_database` |
| Prose boundary | Output Sanitizer | draft content `output_sanitizer` |
| State | Chapter State Package | `chapter_state` |
| Structure | Pattern Similarity Checker | `chapter_pattern_report` |
| Facts | Fact Ledger | `fact_ledger` |
| Arc | Arc Planner | `arc_plan` |
| Foreshadowing | Foreshadowing Graph | `foreshadowing_graph` |
| Motif | Motif Budget Manager | `motif_budget_report` |
| Character | Character State Manager / Debt Ledger | `character_state_ledger` |
| Antagonist | Villain Operation Model | `villain_operation_plan` |
| Product polish | Fatigue / Style / Platform / Reward / Review Score | P2 report assets |
| Release | Publishing Gate | `publish_gate_report` plus `revision_task` |

## 4. Priority

P0 implemented:

- Canon Database schema/service/check.
- Output Sanitizer schema-less service integrated into draft and publish gate.
- Chapter State Package schema/service integrated after draft and publish gate.
- Pattern Similarity Checker schema/service.
- Fact Ledger schema/service.
- Publishing Gate integration.
- Fail-to-revision-task generation.

P1 implemented as first deterministic slice:

- `arc_plan`
- `foreshadowing_graph`
- `motif_budget_report`
- `character_state_ledger`
- Debt Ledger inside character state.
- `villain_operation_plan`

P2 implemented as first deterministic slice:

- `reader_fatigue_report`
- `style_control_plan`
- `platform_adapter_report`
- `reward_ledger`
- `review_score_system_report`

## 5. Data Model

Core new schemas:

- `canon_database`: entities, forbidden aliases, alias policy.
- `chapter_state`: active arc, active entities, confirmed facts, open clues, unresolved debts, liabilities, forbidden next.
- `chapter_pattern_report`: structural fingerprint and recent-window checks.
- `fact_ledger`: confirmed chapter facts.
- `arc_plan`: arc question, protagonist/villain goals, required payoffs, forbidden expansion.
- `foreshadowing_graph`: clues, target truths, status, payoff chapter.
- `motif_budget_report`: per-chapter and per-window motif usage.
- `character_state_ledger`: character state and Debt Ledger.
- `villain_operation_plan`: visible agent, hidden goal, signatures, operations.

## 6. Service Design

Implemented service: `src/novel_forge/modules/longform_stability/service.py`

Key functions:

- `sanitize_chapter_text`
- `create_canon_database`
- `check_canon_consistency`
- `create_arc_plan`
- `create_chapter_state_package`
- `require_chapter_state_for_generation`
- `create_chapter_pattern_report`
- `create_fact_ledger`
- `create_motif_budget_report`
- `create_character_state_ledger`
- `create_foreshadowing_graph`
- `create_villain_operation_plan`
- `create_longform_artifacts_for_draft`
- `evaluate_longform_stability_gate`
- `create_revision_task_from_gate`

## 7. Quality Gate Design

Publishing Gate now includes:

- canon database present;
- canon consistency;
- output sanitizer;
- chapter state presence;
- fact ledger presence;
- pattern similarity;
- motif budget;
- arc progress;
- foreshadowing graph;
- character state/debt;
- villain operation;
- review score.

Gate output remains compatible with existing schema:

```json
{
  "decision": "blocked",
  "gates": {
    "longform_stability_passed": false
  },
  "blocking_issues": []
}
```

Every blocked gate creates a `revision_task`.

## 8. Review Flow

Existing flow remains:

```text
draft -> review -> revision_task -> revision_plan -> editor_patch -> draft_version -> re-review -> publish_gate
```

New flow adds:

```text
draft -> output_sanitizer -> chapter_state -> pattern/fact/motif/debt/foreshadow/villain reports -> publish_gate -> revision_task
```

## 9. Auto Revision Flow

Failed gate issues are normalized into revision task issues:

- `dimension`
- `severity`
- `message`
- `recommendation`
- `status=open`

This converts natural-language review and deterministic gate failures into executable work.

## 10. Test Plan

Implemented tests:

- sanitizer blocks JSON notes and extracts text;
- canon forbidden alias fails;
- repeated pattern fails;
- publish gate writes revision task for long-form failures;
- missing preexisting chapter state fails gate;
- schema count and new type registration.

Additional recommended tests:

- 50-chapter fixture with synthetic state/pattern history;
- arc payoff window tests for chapter 10/20/30;
- villain action cadence tests;
- motif budget configured per genre.

## 11. Migration Plan

1. Generate a project-level `canon_database` from existing bibles and approved names.
2. Create `arc_plan` for each active volume.
3. Run long-form artifact generation over existing canonical drafts.
4. Mark chapters with sanitizer/canon/pattern failures as non-canonical candidates.
5. Convert gate failures into revision tasks.
6. Re-run publish gate after revision.

## 12. Acceptance Criteria

| Requirement | Status |
|---|---|
| forbidden aliases fail | Implemented and tested |
| JSON/notes metadata fail | Implemented and tested |
| chapter state after draft | Implemented |
| missing state fails gate | Implemented and tested |
| repeated pattern fails | Implemented and tested |
| motif budget report | Implemented |
| arc question gate | Implemented |
| foreshadowing target truth gate | Implemented |
| Debt Ledger | Implemented |
| villain operation model | Implemented |
| publish gate creates revision_task | Implemented and tested |
| all new modules have tests | Unit tests added for critical P0 paths |

## 13. Roadmap

Next iteration:

- Add UI panels for Canon, Chapter State, Motif Budget, and Gate Reasons.
- Add configurable rule packs per project/genre.
- Add model-assisted extraction behind deterministic validation.
- Backfill longform stability assets for `generated/longchain-webnovel`.
- Add end-to-end fixture covering 10 chapters with payoffs and villain actions.
