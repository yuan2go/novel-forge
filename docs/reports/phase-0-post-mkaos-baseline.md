# Phase 0 Post-MKAOS Baseline Report

生成时间：2026-07-03

## 1. 目标

Phase 0 的目标是把 Novel OS v6 工业化文档从“MKAOS P0 完全完成”修正为“MKAOS P0 有条件完成”，并把后续执行顺序调整为先补防回退测试、生产契约、selector/Canon、Context Builder 和 ReviewIssue，再进入 Loop、Longform Recap、Agent Center、UI、Publish/Feedback 和最终压力测试。

本阶段只修改文档和报告，不修改业务代码。

## 2. 输入文档

已读取并作为基线：

| 文档 | 用途 |
| -- | -- |
| `docs/design/novel-os-v6-industrialization-design.md` | 现有 Post-MKAOS 工业化设计，需要修正基线和 Phase 顺序。 |
| `docs/prompts/claude-code-novel-os-v6-long-task-prompts.md` | 长任务提示词，需要修正“MKAOS 已完成”措辞和后续执行顺序。 |
| `docs/reports/mkaos-docs-index.md` | 原始 MKAOS 设计文档索引。 |
| `docs/reports/mkaos-docs-vs-implementation-audit.md` | 原始设计 vs 当前实现审计，给出 78/100 和有条件完成结论。 |
| `docs/reports/mkaos-gap-and-risk-register.md` | 缺口与风险登记。 |
| `docs/reports/mkaos-remediation-plan.md` | 修复与工业化接入计划。 |

## 3. 基线结论

当前 MKAOS P0 状态为：

```text
总体一致性评分：78/100
P0 状态：有条件完成
```

有条件完成的条件：

1. Canon conflict 仍是基础检查。
2. warning fallback 仅限 compat/dev/sample。
3. MKAOS 尚未统一进入 Context Builder。
4. MKAOS 尚未统一进入 OS Envelope。
5. MKAOS issue 尚未统一进入 ReviewIssue。
6. 需要补 RAG / source leakage 回归测试。

## 4. 文档修改

| 文件 | 修改内容 |
| -- | -- |
| `docs/design/novel-os-v6-industrialization-design.md` | 将当前基线改为 78/100、有条件完成；列出条件和缺口；把 Phase 顺序调整为 0-12；补入 Phase 1 RAG/source leakage；更新提交计划和最终判断。 |
| `docs/prompts/claude-code-novel-os-v6-long-task-prompts.md` | 将提示词中的“P0 已完成”改为“有条件完成”；新增审计条件；将执行顺序调整为 RAG/source leakage -> OS Envelope -> selector/Canon -> Context Builder -> ReviewIssue；修正分支名。 |
| `docs/reports/phase-0-post-mkaos-baseline.md` | 新增本阶段报告。 |

## 5. 后续 Phase 顺序

```text
Phase 0：文档基线修正
Phase 1：RAG/source leakage 回归测试
Phase 2：OS Envelope 标准化与 MKAOS 接入
Phase 3：MKAOS selector / Canon conflict 加固
Phase 4：Context Builder 统一入口
Phase 5：ReviewIssue 阻断系统
Phase 6：Loop Engineering Kernel
Phase 7：Longform Recap Agent
Phase 8：Agent Center
Phase 9：UI 可编辑控制台
Phase 10：Publish / Feedback 闭环
Phase 11：12 章压力测试与 Provider hard-stop proof
Phase 12：最终复盘与工业化差距报告
```

## 6. 取舍

1. 未在 Phase 0 修改业务代码，避免把基线修正与功能实现混在同一个 commit。
2. 未重写 MKAOS P0 文档和审计报告，只把它们设为后续执行的真实依据。
3. 详细设计文档保留原有模块设计内容，但 Phase 标题和执行顺序已按最新审计结果修正。
4. 原始 MKAOS 审计四份报告仍作为独立证据文件提交，后续 Phase 不再重复做同一审计。

## 7. 验收

本阶段按要求运行了 Git diff 检查，确认只涉及文档和报告文件。

业务测试未运行；Phase 0 是 docs-only 变更，下一阶段会从 RAG/source leakage 专项测试开始。

## 8. 风险

| 风险 | 处理 |
| -- | -- |
| 设计文档原有章节内容较长，局部编号可能仍保留历史段落编号。 | Phase 标题和执行顺序已修正；后续阶段按 Phase 0 新顺序执行。 |
| MKAOS 审计报告原本未提交。 | Phase 0 commit 将一并提交四份审计报告和本阶段基线修正，形成可追溯基线。 |
