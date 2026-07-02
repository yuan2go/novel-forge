# Test Novel System Diagnosis

## Translation From Text Problems To System Defects

```text
小说文本问题
↓
系统缺陷
↓
新增模块
↓
代码改动
↓
测试
↓
验收
```

| 小说文本问题 | 系统缺陷 | 新增模块 | Code | Tests | Acceptance |
|---|---|---|---|---|---|
| 主角名漂移 | No canonical identity lock | Canon Database | `modules/longform_stability`, `canon_database` schema | `test_canon_database_fails_forbidden_alias` | forbidden alias fails gate |
| JSON/notes 泄漏 | No prose sanitizer | Output Sanitizer | `sanitize_chapter_text`, draft and publish gate integration | `test_output_sanitizer_blocks_json_notes_and_extracts_text` | JSON wrappers blocked |
| 状态不连续 | No chapter state package | Chapter State Package | `chapter_state` schema and generation after draft | `test_evaluate_gate_requires_preexisting_chapter_state` | missing state fails gate |
| 模板重复 | No structural fingerprint | Pattern Similarity Checker | `chapter_pattern_report` | `test_pattern_checker_fails_repeated...` | three repeated methods fail |
| 线索无限扩张 | Clues lack target truths | Foreshadowing Graph | `foreshadowing_graph` | longform gate tests | new clues without target truth fail |
| 母题过载 | No motif budget | Motif Budget Manager | `motif_budget_report` | longform gate tests | over-budget warning/fail |
| 师父债滥用 | No debt ledger | Character State Manager | `character_state_ledger` | longform gate tests | liabilities recorded |
| 反派缺席 | No villain cadence | Villain Operation Model | `villain_operation_plan` | longform gate tests | missing agent/action becomes gate issue |
| 审稿不可执行 | Review issues not always tasks | Revision Task Generator | `create_revision_task_from_gate` | `test_publish_gate_writes_revision_task...` | fail gate writes revision_task |

## Root Cause

The previous system evaluated whether a chapter was plausible and well written, but did not treat the long novel as a stateful controlled process. Generation was allowed to create new names, clues, debts, motifs, and institutions faster than the runtime could validate or pay them off.

## Required Operating Principle

Every chapter must be a state transition, not just a text artifact.

Therefore every generated chapter now needs:

- prose sanitization result;
- canon consistency result;
- chapter state package;
- pattern fingerprint;
- motif usage;
- fact ledger;
- character/debt updates;
- foreshadowing updates;
- villain operation evidence;
- publishing gate decision;
- revision task when blocked.
