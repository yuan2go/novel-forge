# Novel OS v6.1 工业化落地设计文档：MKAOS P0 完成后的系统补全方案

> 适用对象：`yuan2go/novel-forge` 仓库 `v6` 分支。  
> 当前基线：多学科知识资产操作系统（MKAOS）P0 经原始设计审计后为 **有条件完成**，总体一致性评分 **78/100**。  
> 本文目标：在不重复实现 MKAOS P0 的前提下，先修正 RAG/source leakage、OS Envelope、MKAOS selector/Canon、Context Builder 和 ReviewIssue 等工业化缺口，再继续推进 Loop Engineering、长篇复盘 Agent、Agent Center、UI 控制台、发布与反馈闭环。

---

## 0. 文档定位

本文不是重新设计一个新项目，也不是让 Claude Code 重做 MKAOS。  
本文是 **MKAOS P0 有条件完成后的增量工业化设计文档**，用于指导 Claude Code 在当前 `v6` 分支继续执行长任务。

核心原则：

```text
不要重复实现 MKAOS。
不要另起炉灶。
先审计当前实现，再补齐工业化缺口。
把已有能力从“可用”推进到“不可绕过、可验收、可回滚、可观测”。
```

---

## 1. 当前最新工程基线

根据 `docs/reports/mkaos-docs-vs-implementation-audit.md`、`docs/reports/mkaos-gap-and-risk-register.md` 和 `docs/reports/mkaos-remediation-plan.md`，MKAOS 当前实现满足 P0 最小闭环，但不能宣称为完整 MKAOS 或生产级 Novel OS 知识底座。

审计结论：

```text
总体一致性评分：78/100
P0 状态：有条件完成
不允许重复实现 MKAOS P0
不允许跳过 RAG isolation、Canon、Context Builder 后直接扩展长篇功能
```

有条件完成的条件：

1. Canon conflict 仍是基础检查，必须在后续接入真实 Canon / Character / Arc / Foreshadowing / WorldRule 数据。
2. Pack 构造失败 warning fallback 仅限 compat/dev/sample 路径；production canonical chapter 和 release package 必须 fail closed 或进入 human gate。
3. MKAOS 尚未统一进入 Context Builder；四个生产服务仍存在直接构造 Knowledge Pack 的路径。
4. MKAOS 尚未统一进入 OS Envelope；mutation、pack build、usage、feedback 需要 trace、policy 和 source_policy。
5. MKAOS validation/canon issue 尚未统一进入 ReviewIssue；blocking 还不能稳定阻断 canonical chapter 和 release package。
6. RAG / source leakage 需要专项回归，覆盖 Prose pack、prompt preview、chapter prompt、publish pack、recap context 和 runtime asset。

### 1.1 MKAOS P0 已实现范围

已实现 M1-M9：

| 编号 | 能力 | 状态 |
|---|---|---|
| M1 | 模型 / schema | P0 已实现 |
| M2 | migration | P0 已实现 |
| M3 | 来源导入清洗 | P0 已实现，需补 leakage 回归 |
| M4 | Knowledge Card | P0 已实现，selector/quality 需加固 |
| M5 | 用途绑定 | P0 已实现，revision/recap/publish/feedback flow 待补 |
| M6 | Rule Card / Template Card | P0 已实现，需接 ReviewIssue |
| M7 | Knowledge Pack Builder | P0 已实现，selector、budget、risk、production fallback 需加固 |
| M8 | 4 个 Flow Adapter | P0 已实现，需统一到 Context Builder |
| M9 | 校验 API、反百科化 / Canon stub、Usage / Feedback、最小 UI、回归验收 | P0 已实现，Canon/feedback/issue 治理需加固 |

### 1.2 已完成的核心文件

| 类型 | 文件 |
|---|---|
| 后端核心 | `src/novel_forge/modules/mkaos/service.py` |
| API | `src/novel_forge/api/routers/mkaos.py` |
| Migration | `src/novel_forge/storage/migrations/versions/v20260702_0003_mkaos_p0.py` |
| UI | `web/admin/app/features/mkaos/MkaosConsolePage.tsx` |
| 测试 | `tests/unit/test_mkaos.py` |

### 1.3 已新增数据表

```text
source_documents
source_chunks
knowledge_cards
knowledge_usage_bindings
rule_cards
template_cards
knowledge_packs
knowledge_pack_items
knowledge_usage_events
knowledge_quality_scores
```

这些表已经构成 MKAOS P0 的资产存储、知识卡、规则卡、模板卡、Pack、Usage 和 Feedback 基础。

### 1.4 已新增 API

```text
/api/mkaos/sources*
/api/mkaos/knowledge*
/api/mkaos/usage-bindings*
/api/mkaos/rules
/api/mkaos/templates
/api/mkaos/packs/build
/api/mkaos/packs/{id}
/api/mkaos/packs/{id}/prompt-preview
/api/mkaos/validate/artifact
/api/mkaos/validate/canon-conflict
/api/mkaos/usage-events
/api/mkaos/feedback/review
/api/mkaos/feedback/apply-weight-update
/api/mkaos/risks
/api/mkaos/acceptance/minimal
```

### 1.5 已接入 Agent / Flow

已完成的 Flow Adapter：

| Flow | 当前状态 |
|---|---|
| Outline | 已接入 Knowledge Pack |
| ChapterOutline | 已接入 Knowledge Pack |
| Prose | 已接入 Knowledge Pack |
| Review | 已接入 Knowledge Pack |

关键约束：

```text
Prose pack 强制不包含 source_chunk.raw_text。
生成后记录 usage event。
Review 注入 MKAOS 校验 issue。
Review 支持 feedback / weight 回写。
Pack 构造失败时 warning 降级，不破坏旧流程。
```

### 1.6 已完成 UI

已新增 `/mkaos` 管理台，支持：

```text
来源导入
知识卡创建 / 编辑
绑定管理
Pack 构造预览
规则库
usage events
风险知识列表
P0 验收 fixture
```

### 1.7 当前测试结果

已验证：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
# 266 tests OK, skipped=1

python3 -m unittest tests.integration.test_pipeline
# OK，包含 sample pipeline 二次幂等复跑

npm --prefix web/admin test
# OK，Playwright smoke 因未安装 Playwright 按项目现状跳过

npm --prefix web/admin run build
# OK，包含 /mkaos route
```

### 1.8 已跑通最小验收样例

土地兼并样例已跑通：

```text
生成 Knowledge Card：土地兼并
绑定 outline / chapter_outline / prose / review
生成制度有效性 Rule Card
生成地方土地案 Template Card
Outline / Prose / Review Pack 均包含对应知识与规则
Prose Pack source isolation = true
Usage event 可写入
feedback weight update 可写入
```

### 1.9 已知取舍与遗留风险

| 风险 / 取舍 | 当前状态 | 后续要求 |
|---|---|---|
| 原始 MKAOS 文档已拉取并完成审计 | 审计报告已生成，结论为 78/100、有条件完成 | 后续设计和提示词必须以审计报告为基线 |
| Canon 冲突使用基础检查 | P0 可接受但不是完整 Canon 治理 | 需要在后续接入真实 Canon / Character / Arc / Foreshadowing / WorldRule 数据 |
| Pack 构造失败 warning 降级 | 保持旧流程兼容 | production canonical chapter / release package 需要按 policy fail closed 或 human gate |
| 运行资产和 Agent runtime 资产已从 generation RAG 隔离 | 策略存在 | 必须加入专项回归测试，防止后续污染 |
| Prose source isolation | 已实现 | 必须升级为生产级强约束和泄漏检测 |
| Context Builder 未统一接入 | 直接调用路径仍存在 | 必须在 Context Builder 阶段收敛为统一上下文入口 |
| OS Envelope 未覆盖 MKAOS 全路径 | 需要新增标准 envelope 和 enforcement | mutation、pack build、usage、feedback 缺 envelope 时 production fail closed |
| ReviewIssue 未统一接收 MKAOS issue | Review 中目前为局部合并 | 必须进入统一 issue asset 和 blocking gate |

---

## 2. 更新后的总体落地顺序

审计后顺序以“先补防回退测试，再接生产契约，再统一上下文和阻断系统”为准。原计划中的“MKAOS”不再重做，只做生产级加固。

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

关键变化：

```text
MKAOS 从“待建设模块”变为“有条件完成 P0 的知识底座”。
后续重点不再是建表和 CRUD，而是防泄漏测试、生产契约、selector/Canon、上下文统一、质量阻断、循环治理、复盘回写。
任何长篇复盘、Agent Center、UI 或发布扩展，都不得绕过 RAG isolation、Canon、Context Builder 和 ReviewIssue。
```

---

## 3. 总体技术目标

### 3.1 工程目标

把当前 v6 从：

```text
Novel OS early runtime + MKAOS P0 knowledge layer
```

推进到：

```text
Novel OS production-grade longform control layer
```

### 3.2 系统目标

| 能力 | 目标 |
|---|---|
| OS Envelope | 所有生产写入、模型调用、发布、反馈、MKAOS 资产变更都必须带 envelope / trace / runtime policy |
| MKAOS | 从 P0 最小闭环升级为所有 Agent 的统一知识底座，避免重复建设 |
| Context Builder | 所有 Agent 不再自行拼接上下文，统一通过 task-specific Context Bundle |
| Eval / Review Issue | 所有质量问题结构化、可定位、可阻断、可回写、可生成修订任务 |
| Loop Engineering | 生成、审稿、修订、复盘、反馈成为可循环、可中止、可恢复、可回滚的流程 |
| 长篇复盘 Agent | 每 10 章 / 每卷复盘，能对比记忆库并回写 Canon / Character / Foreshadowing / Issue / RevisionTask |
| Agent Center | 可观察 Agent run graph、gate timeline、budget burn、dead-letter、resume |
| UI 可编辑控制台 | Canon / Arc / Character / Foreshadowing / Villain / Motif / Issue / MKAOS 可人工编辑、审计、版本化 |
| 反馈发布闭环 | 发布前 gate、平台 adapter、读者反馈聚类、反馈回写、rollback rehearsal |

---

## 4. 更新后的系统架构

```text
Novel OS v6.1+
│
├── 1. OS Contract Layer
│   ├── OS Envelope
│   ├── Operation Registry
│   ├── Runtime Policy
│   ├── Write Path Guard
│   ├── Model Call Guard
│   ├── Provider Guard
│   └── Enforcement Audit
│
├── 2. MKAOS Knowledge Asset Layer 〔已完成 P0，后续加固〕
│   ├── source_documents
│   ├── source_chunks
│   ├── knowledge_cards
│   ├── rule_cards
│   ├── template_cards
│   ├── knowledge_packs
│   ├── knowledge_usage_bindings
│   ├── knowledge_usage_events
│   ├── knowledge_quality_scores
│   ├── Knowledge Pack Builder
│   ├── Flow Adapters: outline / chapter_outline / prose / review
│   └── 后续扩展: recap / revision / publish / feedback adapters
│
├── 3. Canon & Longform Memory Layer
│   ├── Canon
│   ├── Arc
│   ├── Character Ledger
│   ├── Foreshadowing Ledger
│   ├── Fact Ledger
│   ├── Motif Budget
│   ├── Villain Operation
│   ├── Timeline
│   └── Issue History
│
├── 4. Context Layer
│   ├── Context Builder
│   ├── Context Bundle
│   ├── MKAOS Knowledge Pack Adapter
│   ├── Context Budget Manager
│   ├── Source Isolation Filter
│   ├── Evidence Trace
│   └── Required Asset Policy
│
├── 5. Evaluation Layer
│   ├── ReviewIssue
│   ├── IssueEvidence
│   ├── IssueBlockingPolicy
│   ├── Longform Stability Gate
│   ├── MKAOS Validation Issue
│   ├── Knowledge Consistency Gate
│   ├── Platform Compliance Gate
│   └── RevisionTask Generator
│
├── 6. Loop Layer
│   ├── LoopRun
│   ├── LoopStep
│   ├── LoopCheckpoint
│   ├── LoopBudget
│   ├── Stop Condition
│   ├── Retry / Dead-letter
│   ├── Resume / Rollback
│   └── Loop Report
│
├── 7. Agent Layer
│   ├── Chief Editor Agent
│   ├── Outline Agent
│   ├── Chapter Outline Agent
│   ├── Prose Agent
│   ├── Review Agent
│   ├── Longform Recap Agent
│   ├── Feedback Agent
│   └── Publishing Agent
│
├── 8. Product UI Layer
│   ├── MKAOS Console 〔已完成最小 UI〕
│   ├── Canon Console
│   ├── Arc Console
│   ├── Character Console
│   ├── Foreshadow Console
│   ├── Villain Console
│   ├── Motif Budget Console
│   ├── Review Issue Center
│   ├── Longform Recap Report Page
│   ├── Agent Center
│   └── Publishing / Feedback Console
│
└── 9. Acceptance & Ops Layer
    ├── Unit Tests
    ├── Integration Pipeline
    ├── 12-chapter Pressure Test
    ├── 30-chapter Acceptance Test
    ├── Provider Hard-stop Proof
    ├── RAG Isolation Regression
    ├── Source Isolation Regression
    ├── Rollback Rehearsal
    └── Industrialization Gap Report
```

---

# 5. Phase 0：文档基线修正

## 5.1 技术目标

在继续开发前，必须把 MKAOS 完成后的真实工程状态冻结成基线，避免 Claude Code 重复建设或误判缺口。

## 5.2 必须输出文档

```text
docs/reports/v6-current-state-after-mkaos.md
docs/reports/mkaos-p0-implementation-report.md
docs/reports/v6-industrialization-plan-after-mkaos.md
docs/reports/v6-risk-register-after-mkaos.md
```

## 5.3 审计重点

| 审计项 | 要求 |
|---|---|
| MKAOS schema | 确认 migration、表、字段、索引、project scope、lineage |
| MKAOS service | 确认导入、知识卡、规则卡、模板卡、Pack、usage、feedback |
| MKAOS API | 确认路由、参数校验、权限边界、错误处理 |
| Flow Adapter | 确认 outline / chapter_outline / prose / review 真实接入 |
| Source Isolation | 确认 Prose Pack 不暴露 `source_chunk.raw_text` |
| RAG Isolation | 确认 MKAOS 运行资产和 Agent runtime 资产不污染 generation RAG |
| Context Budget | 确认 Pack 构造不会突破上下文预算 |
| Pipeline Idempotency | 确认 sample pipeline 二次复跑幂等 |
| Project Scope Lineage | 确认知识资产不会跨项目误污染 |
| Canon Stub | 标记为 P1 需要真实接入 |
| Warning Fallback | 标记为 P0 兼容，生产模式需要 policy 化 |

## 5.4 验收标准

```text
1. 不允许重新创建已有 MKAOS 模型、表、API。
2. 所有后续任务必须引用当前 MKAOS 作为既有底座。
3. 必须明确哪些是已完成、哪些是待加固、哪些是 P1/P2。
4. 文档必须包含文件路径、测试命令和测试结果。
```

---

# 6. Phase 1：RAG / Source Leakage 回归测试

## 6.1 技术目标

先补最危险的防回退测试，确保后续 Context Builder、Publish、Recap 和 Agent Center 扩展不会把 `source_chunk.raw_text` 或 MKAOS runtime asset 带入生成链路。

必须覆盖：

```text
RAG bucket isolation
source_chunk.raw_text 不进入 Prose pack
source_chunk.raw_text 不进入 prompt preview
source_chunk.raw_text 不进入 chapter prompt
source_chunk.raw_text 不进入 publish pack
source_chunk.raw_text 不进入 recap context
runtime asset 不污染 generation RAG
MKAOS pack budget regression
project-scoped lineage regression
```

## 6.2 验收标准

1. 新增 RAG / source leakage 专项测试。
2. `source_chunk.raw_text` 不进入 prose、prompt preview、chapter prompt、publish pack、recap context。
3. generation RAG 不检索 `knowledge_pack`、`knowledge_usage_event`、`source_chunk`、`agent_run` 等 runtime asset。
4. 测试结果写入 `docs/reports/phase-1-rag-source-leakage-report.md` 和 `docs/reports/rag-isolation-proof.md`。

# 7. Phase 2：OS Envelope 标准化与 MKAOS 接入

## 6.1 技术目标

OS Envelope 是 Novel OS 的生产契约。MKAOS P0 完成后，下一步优先级应该回到 OS Envelope，因为所有生产资产变更都需要统一治理。

目标：

```text
所有生产写入、模型调用、知识资产变更、审稿问题写入、发布包生成、反馈回流，都必须带 OS Envelope。
```

## 6.2 功能设计

### 6.2.1 Envelope 字段

```json
{
  "envelope_id": "uuid",
  "project_id": "string",
  "operation_id": "string",
  "operation_type": "draft|review|revise|recap|publish|feedback|knowledge_ingest|knowledge_update|context_build|loop_step",
  "asset_type": "chapter|outline|chapter_outline|canon|character|foreshadow|knowledge_card|rule_card|template_card|knowledge_pack|issue|revision_task|release_package|feedback_event",
  "asset_id": "string|null",
  "agent_id": "string|null",
  "workflow_id": "string|null",
  "loop_run_id": "string|null",
  "context_bundle_id": "string|null",
  "knowledge_pack_id": "string|null",
  "model_call_id": "string|null",
  "trace_id": "string",
  "cost_ledger_id": "string|null",
  "provider_policy_id": "string|null",
  "runtime_policy_id": "string",
  "source": {
    "kind": "generated|imported|manual|revised|feedback_backflow|knowledge_ingest",
    "source_id": "string|null",
    "evidence_spans": []
  },
  "quality": {
    "gate_status": "pending|passed|blocked|human_review|required_rework",
    "blocking_issue_ids": [],
    "confidence": 0.0
  },
  "version": {
    "schema_version": "v1",
    "asset_version": 1,
    "parent_asset_version": "string|null"
  }
}
```

### 6.2.2 Operation Registry

必须建立 operation registry，用于声明每类操作的强制要求。

| operation_type | must_have_context | must_have_model_guard | must_have_gate | allow_warning_fallback | production_policy |
|---|---:|---:|---:|---:|---|
| knowledge_ingest | false | false | true | false | envelope_required |
| knowledge_update | false | false | true | false | envelope_required |
| context_build | false | false | false | false | trace_required |
| outline | true | true | true | false | fail_closed |
| chapter_outline | true | true | true | false | fail_closed |
| prose | true | true | true | false | fail_closed |
| review | true | true | true | false | fail_closed |
| revision | true | true | true | false | fail_closed |
| recap | true | true | true | false | fail_closed |
| publish | true | false | true | false | fail_closed |
| feedback | false | false | true | true | guarded_write |

重点：当前 MKAOS Pack 构造失败时 warning 降级可以保留在兼容模式，但生产路径必须通过 runtime policy 决定：

```text
local/dev/sample pipeline：允许 warning fallback。
production/canonical chapter/release package：不允许 warning fallback，必须 fail closed 或 human gate。
```

## 6.3 实现细节

### 6.3.1 需要接入的路径

```text
API routers
CLI commands
workflow processors
agent tasks
MKAOS API mutations
MKAOS pack build
outline generation
chapter outline generation
prose generation
review services
revision services
longform recap services
editor save path
publishing services
feedback mutation services
release package generation
```

### 6.3.2 Enforcement Audit 报告

必须输出：

```text
docs/reports/os-enforcement-audit-after-mkaos.md
```

表格字段：

```text
Path
Type
Mutates Production
Calls Model
Reads MKAOS
Writes MKAOS
Has OS Envelope
Has Context Bundle
Has Knowledge Pack
Has Trace
Has Cost Ledger
Has Provider Guard
Has Gate
Fallback Policy
Status
Required Fix
```

## 6.4 验收标准

```text
1. 缺失 OS Envelope 的生产写入必须 fail closed。
2. MKAOS mutation API 必须具备 envelope / trace / project scope。
3. canonical chapter 写入必须具备 context_bundle_id、knowledge_pack_id、trace_id、gate_status。
4. release package 生成必须检查 blocking issues。
5. 所有 needs_fix 生产路径必须被修复或显式标记为 non-production。
```

---

# 8. Phase 3：MKAOS Selector / Canon Conflict 加固

## 7.1 技术目标

MKAOS P0 已经完成。后续不再重做，而是完成生产级加固：

```text
把 MKAOS 从“可用知识系统”升级为“Novel OS 不可绕过的知识底座”。
```

## 7.2 不允许重复实现的内容

不得重复创建以下内容：

```text
src/novel_forge/modules/mkaos/service.py
src/novel_forge/api/routers/mkaos.py
v20260702_0003_mkaos_p0.py
source_documents
source_chunks
knowledge_cards
knowledge_usage_bindings
rule_cards
template_cards
knowledge_packs
knowledge_pack_items
knowledge_usage_events
knowledge_quality_scores
web/admin/app/features/mkaos/MkaosConsolePage.tsx
tests/unit/test_mkaos.py
```

如需修改，必须做兼容扩展和 migration，不得破坏已有测试。

## 7.3 需要补强的能力

### 7.3.1 Recap / Revision / Publish / Feedback Adapter

当前已接入：

```text
outline
chapter_outline
prose
review
```

需要新增或补全：

```text
revision
recap
publish
feedback
```

#### recap pack 必须包含

```text
叙事结构规则
人物一致性规则
伏笔回收规则
战力 / 资源约束
逻辑一致性规则
章节节奏规则
平台读者期待规则
Issue 历史相关规则
```

#### revision pack 必须包含

```text
原问题
修复目标
不可破坏设定
相关 Canon / Character / Foreshadowing
相关知识卡 / 规则卡 / 模板卡
```

#### publish pack 必须包含

```text
平台规则
合规规则
书名 / 简介 / 封面 / 章节排版规则
AI 味 / 重复 / 低质检测规则
release gate 规则
```

#### feedback pack 必须包含

```text
读者反馈聚类规则
情绪分类规则
章节定位规则
人设 / 节奏 / 爽点 / 逻辑归因规则
可回写权重规则
```

### 7.3.2 Canon Stub 升级

当前 Canon 冲突使用兼容 stub。后续必须接入真实数据：

```text
Canon
Character Ledger
Arc
Foreshadowing Ledger
Fact Ledger
Motif Budget
Villain Operation
Timeline
```

Canon conflict validator 需要支持：

| 检查类型 | 示例 |
|---|---|
| 世界观冲突 | 已设定禁术不可复活，后文直接复活 |
| 人物冲突 | 谨慎型角色无理由冒险 |
| 时间线冲突 | 同一角色同时出现在两地 |
| 伏笔冲突 | 未铺垫道具突然成为关键解法 |
| 战力冲突 | 低阶角色无代价击败高阶角色 |
| 制度冲突 | 世界制度不允许的行为被默认通过 |

### 7.3.3 Source Isolation 加固

当前 Prose Pack 已强制不包含 `source_chunk.raw_text`。后续需要：

```text
1. 将 source isolation 变成独立 filter。
2. 所有 prose / chapter / publish 生产包必须执行 source isolation。
3. 测试 raw_text、长段原文、source chunk hash 泄漏。
4. 对 prompt preview 也执行隔离策略。
```

### 7.3.4 RAG Bucket 隔离保持

已修复：MKAOS 运行资产和 Agent runtime 资产从 generation RAG 中隔离。

后续要求：

```text
1. 形成 RAG bucket policy 文档。
2. 新增回归测试。
3. 禁止运行报告、trace、usage event、agent runtime 被 generation RAG 检索到。
4. 允许经过人工确认的知识卡、规则卡、模板卡进入生产知识包。
```

## 7.4 验收标准

```text
1. MKAOS 现有 266+ unit tests 不回退。
2. sample pipeline 二次幂等复跑仍通过。
3. recap / revision / publish / feedback 至少有 adapter 或 policy stub，并具备测试。
4. production prose pack 不能出现 source_chunk.raw_text。
5. MKAOS pack build 与 OS Envelope / Context Builder 打通。
```

---

# 9. Phase 4：Context Builder 统一入口

## 8.1 技术目标

MKAOS P0 已经提供知识包，但 Novel OS 仍需要一个统一 Context Builder 来解决：

```text
每个 Agent 到底应该拿哪些上下文？
上下文超预算时如何压缩？
哪些资产是 required？
哪些资产缺失会 fail closed？
MKAOS Knowledge Pack 如何进入模型调用？
```

## 8.2 Context Bundle 类型

```text
outline_context
detail_outline_context
chapter_context
prose_context
review_context
revision_context
recap_context
publish_context
feedback_context
```

## 8.3 通用结构

```json
{
  "context_bundle_id": "uuid",
  "project_id": "string",
  "task_type": "prose|review|recap|publish|feedback",
  "operation_id": "string",
  "required_assets_status": "complete|missing|required_human_gate",
  "canon_context": {},
  "arc_context": {},
  "character_context": {},
  "foreshadowing_context": {},
  "fact_ledger_context": {},
  "motif_budget_context": {},
  "villain_context": {},
  "chapter_history": [],
  "issue_history": [],
  "mkaos": {
    "knowledge_pack_id": "string",
    "knowledge_cards": [],
    "rule_cards": [],
    "template_cards": [],
    "source_isolation": true
  },
  "budget": {
    "max_tokens": 0,
    "estimated_tokens": 0,
    "compression_strategy": "none|summary|ranked|strict"
  },
  "forbidden_changes": [],
  "evidence_trace": []
}
```

## 8.4 Task Policy

| task_type | required assets | MKAOS Pack | fail policy |
|---|---|---|---|
| outline | project premise, genre, target platform | outline pack | human gate |
| chapter_outline | outline, arc, chapter goal | chapter_outline pack | fail closed |
| prose | chapter_outline, canon, character, style, forbidden_changes | prose pack | fail closed |
| review | target text, review rules, platform rules | review pack | fail closed |
| revision | issue, original text, forbidden_changes | revision pack | fail closed |
| recap | chapter summaries, canon, character, foreshadow, issue history | recap pack | fail closed |
| publish | final chapters, metadata, review gates | publish pack | fail closed |
| feedback | feedback events, release metadata | feedback pack | guarded write |

## 8.5 上下文预算策略

上下文构建必须防止无限堆知识。

推荐策略：

```text
1. required assets 优先。
2. 当前章节相关资产优先。
3. blocking issue 相关资产优先。
4. 高权重 knowledge cards 优先。
5. 最近 usage event 有正反馈的规则优先。
6. source raw text 永远不得进入 prose / publish prompt。
7. 超预算时先压缩历史摘要，再裁剪低置信知识。
```

## 8.6 验收标准

```text
1. 所有模型调用必须记录 context_bundle_id。
2. outline / chapter_outline / prose / review 不得绕过 Context Builder。
3. recap_context 可以读取 MKAOS + Canon + Issue History。
4. 缺失 required assets 时根据 policy fail closed 或 human gate。
5. Context Builder coverage 报告必须输出。
```

---

# 10. Phase 5：ReviewIssue 阻断系统

## 9.1 技术目标

当前系统已有审稿、gate、MKAOS 校验 issue、longform stability first slice。下一步要统一成结构化 Issue 系统。

目标：

```text
质量问题不是报告文本，而是可定位、可阻断、可回写、可修复的系统对象。
```

## 9.2 ReviewIssue Schema

```json
{
  "issue_id": "uuid",
  "project_id": "string",
  "asset_type": "outline|chapter_outline|chapter|canon|knowledge_pack|release_package",
  "asset_id": "string",
  "chapter_no": 0,
  "issue_type": "metadata_leak|canon_drift|character_drift|logic_gap|motif_overuse|foreshadow_missing|foreshadow_forgotten|power_scale_break|mkaos_conflict|platform_violation|ai_tone|repetition|low_quality|reader_fatigue",
  "severity": "info|low|medium|high|critical",
  "blocking": true,
  "evidence": {
    "span": "string|null",
    "related_asset_ids": [],
    "knowledge_card_ids": [],
    "rule_card_ids": [],
    "source": "review|mkaos|longform_gate|platform_gate|feedback"
  },
  "suggested_fix": "string",
  "revision_task_id": "string|null",
  "status": "open|accepted|ignored|fixed|verified|deprecated",
  "created_by": "agent|gate|human",
  "trace_id": "string"
}
```

## 9.3 Blocking Policy

| issue_type | severity | production impact |
|---|---|---|
| metadata_leak | high/critical | 阻断 canonical chapter |
| source_raw_text_leak | critical | 阻断 canonical chapter / release package |
| canon_drift | high/critical | 阻断 canonical chapter |
| character_drift | high/critical | 阻断 canonical chapter |
| logic_gap | high/critical | 阻断 canonical chapter |
| mkaos_conflict | high/critical | 阻断 canonical chapter |
| platform_violation | medium+ | 阻断 release package |
| ai_tone | high/critical | 阻断 release package |
| repetition | high/critical | 阻断 canonical chapter |

## 9.4 MKAOS Issue 接入

Review 已能注入 MKAOS 校验 issue。后续要统一进入 ReviewIssue：

```text
MKAOS validate artifact
MKAOS validate canon-conflict
MKAOS risks
MKAOS feedback review
```

这些结果不能停留在 API 响应里，需要写入 ReviewIssue 或 KnowledgeQualityScore。

## 9.5 RevisionTask Generator

当 blocking issue 出现时，自动生成修订任务。

```json
{
  "revision_task_id": "uuid",
  "project_id": "string",
  "source_issue_ids": [],
  "target_asset_type": "chapter|outline|canon|character|foreshadow",
  "target_asset_id": "string",
  "revision_goal": "string",
  "forbidden_changes": [],
  "context_bundle_id": "string",
  "status": "pending|running|blocked|done|verified"
}
```

## 9.6 验收标准

```text
1. blocking issue 必须阻断 canonical chapter。
2. blocking issue 必须阻断 release package。
3. MKAOS 校验 issue 进入统一 ReviewIssue。
4. high/critical issue 自动生成 RevisionTask。
5. Review Issue Center 可以查询、过滤、更新状态。
```

---

# 11. Phase 6：Loop Engineering Kernel

## 10.1 技术目标

Loop Engineering 不是简单多轮调用模型，而是让 Novel OS 的生产流程变成：

```text
可计划、可执行、可评估、可修订、可中止、可恢复、可回滚。
```

## 10.2 核心数据结构

### LoopRun

```json
{
  "loop_run_id": "uuid",
  "project_id": "string",
  "loop_type": "chapter_review|outline_revision|chapter_revision|longform_recap|feedback_backflow|publish_gate",
  "status": "planned|running|blocked|completed|failed|cancelled|dead_letter",
  "max_steps": 5,
  "current_step": 0,
  "budget": {
    "max_model_calls": 10,
    "max_tokens": 0,
    "max_cost": 0,
    "timeout_seconds": 0
  },
  "stop_conditions": [],
  "checkpoint_ids": [],
  "trace_id": "string"
}
```

### LoopStep

```json
{
  "loop_step_id": "uuid",
  "loop_run_id": "uuid",
  "step_type": "build_context|execute_agent|evaluate|revise|write_back|gate|human_review",
  "status": "pending|running|passed|failed|blocked|skipped",
  "input_asset_ids": [],
  "output_asset_ids": [],
  "context_bundle_id": "string|null",
  "knowledge_pack_id": "string|null",
  "issue_ids": [],
  "checkpoint_id": "string|null",
  "error": "string|null"
}
```

## 10.3 第一批 Loop

优先只做 4 个：

```text
1. Chapter Review Loop
2. Chapter Revision Loop
3. Longform Recap Loop
4. Publish Gate Loop
```

不要一开始做所有自治 Agent。

## 10.4 Loop 决策逻辑

```text
Build Context
  ↓
Execute Agent
  ↓
Evaluate Output
  ↓
Write ReviewIssue
  ↓
如果无 blocking issue：通过
如果有 blocking issue 且未超预算：生成 RevisionTask 并进入 revise
如果有 blocking issue 且超预算：进入 human gate / dead-letter
```

## 10.5 验收标准

```text
1. 每个 LoopRun 都有 step 记录。
2. 每个模型调用都能追溯到 loop_run_id / context_bundle_id / knowledge_pack_id。
3. Loop 超预算必须停止。
4. Loop 失败必须产生 dead-letter 或 human gate。
5. Loop 可以从 checkpoint resume。
```

---

# 12. Phase 7：Longform Recap Agent

## 11.1 技术目标

长篇复盘 Agent 是 Novel OS 的高级治理 Agent，不是普通总结器。

目标：

```text
每 10 章 / 每卷 / 重大转折后，自动复盘当前长篇稳定性，并把结论结构化回写到系统。
```

## 11.2 触发条件

```text
每 10 章
每一卷结束
主线重大转折
人物重大变化
连续 blocking issue 超过阈值
读者反馈出现高频负向聚类
发布前最终检查
```

## 11.3 输入上下文

必须通过 `recap_context` 获取：

```text
全局大纲
分卷大纲
最近 10 章摘要
全部章节摘要索引
Canon
Arc
Character Ledger
Foreshadowing Ledger
Fact Ledger
Motif Budget
Villain Operation
Timeline
ReviewIssue 历史
RevisionTask 历史
MKAOS recap knowledge pack
平台与精品小说审稿规则
```

## 11.4 输出结构

### RecapReport

```json
{
  "recap_report_id": "uuid",
  "project_id": "string",
  "scope": "chapters_1_10|volume_1|pre_publish",
  "chapters": [1, 2, 3],
  "summary": "string",
  "mainline_progress": {},
  "character_changes": [],
  "foreshadowing_changes": [],
  "canon_changes": [],
  "power_scale_changes": [],
  "rhythm_report": {},
  "reader_expectation_report": {},
  "issues": [],
  "revision_tasks": [],
  "memory_update_package": {},
  "chief_editor_notice": [],
  "gate_status": "passed|blocked|human_review"
}
```

## 11.5 回写目标

长篇复盘 Agent 必须能回写：

```text
Canon
Arc
Character Ledger
Foreshadowing Ledger
Fact Ledger
Motif Budget
Villain Operation
ReviewIssue
RevisionTask
KnowledgeUsageEvent
RecapReport
ChiefEditorNotice
```

## 11.6 验收标准

```text
1. 12 章样例可以触发第 10 章复盘。
2. 复盘报告不是纯文本，必须结构化。
3. 人物变化、伏笔变化、Issue、RevisionTask 可以回写。
4. 如果复盘发现 high/critical 问题，后续章节生成必须被阻断或进入 human gate。
5. 总编 Agent 可以读取复盘报告并调整后续计划。
```

---

# 13. Phase 8：Agent Center

## 12.1 技术目标

Agent Center 不应只是 first slice，而要成为 Novel OS 的可观察调度中心。

## 12.2 功能设计

| 能力 | 说明 |
|---|---|
| Agent Registry | 登记所有 Agent 能力、输入输出、依赖、权限 |
| Run Graph | 展示任务从 context → model → gate → writeback 的链路 |
| Gate Timeline | 展示各 gate 的通过 / 阻断 / human review |
| Budget Burn | 展示 token / cost / call 次数 |
| Dead-letter Queue | 失败任务归档与重试 |
| Resume | 从 checkpoint 恢复 Loop |
| Manual Override | 人工批准、驳回、回滚 |
| Chief Editor Inbox | 总编 Agent 收到复盘、问题、发布风险 |

## 12.3 验收标准

```text
1. Agent run 可以查到 OS Envelope、Context Bundle、Knowledge Pack、ReviewIssue。
2. LoopRun 状态可以在 Agent Center 查看。
3. dead-letter 可以重试或关闭。
4. high/critical issue 会出现在 Chief Editor Inbox。
```

---

# 14. Phase 9：UI 可编辑控制台

## 13.1 技术目标

当前已有 `/mkaos` 最小管理台。后续 UI 重点不是美化，而是让核心资产可编辑、可审计、可版本化。

## 13.2 优先级

| 优先级 | 页面 |
|---|---|
| P0 | Review Issue Center |
| P0 | Longform Recap Report Page |
| P0 | Agent Center |
| P1 | Canon Console |
| P1 | Character Console |
| P1 | Foreshadowing Console |
| P1 | Arc Console |
| P1 | Motif Budget Console |
| P1 | Villain Console |
| P1 | Publishing / Feedback Console |

## 13.3 每个控制台通用要求

```text
列表
详情
创建 / 编辑
版本历史
引用关系
相关 Issue
相关 LoopRun
审计日志
回滚入口
```

## 13.4 MKAOS UI 后续增强

当前 `/mkaos` 已支持最小 UI。后续增强：

```text
1. Knowledge Pack 使用影响分析。
2. Knowledge Quality Score 趋势。
3. 高风险知识列表与处理状态。
4. 与 ReviewIssue 的关联展示。
5. Source isolation 检查结果展示。
6. RAG bucket policy 展示。
```

---

# 15. Phase 10：Publish / Feedback 闭环

## 14.1 技术目标

发布与反馈不是最后的“导出功能”，而是 Novel OS 的外部验证闭环。

## 14.2 发布前门禁

Release Package 生成必须检查：

```text
OS Envelope
Context Bundle
ReviewIssue blocking 状态
Longform Stability Gate
MKAOS platform rule pack
AI 味 / 重复 / 水文
平台规则
章节排版
书名 / 简介 / 标签 / 封面元数据
```

## 14.3 反馈回流

FeedbackEvent：

```json
{
  "feedback_event_id": "uuid",
  "project_id": "string",
  "platform": "qidian|fanqie|jjwxc|custom",
  "source_type": "comment|chapter_follow|collection|retention|manual_note",
  "chapter_no": 0,
  "raw_feedback": "string",
  "sentiment": "positive|neutral|negative|mixed",
  "topic_tags": [],
  "mapped_issue_type": "rhythm|character|logic|style|hook|platform_fit|null",
  "confidence": 0.0,
  "action": "ignore|create_issue|adjust_weight|create_revision_task|notify_editor"
}
```

## 14.4 与 MKAOS 的关系

反馈可以影响：

```text
KnowledgeQualityScore
KnowledgeUsageBinding weight
RuleCard effective score
TemplateCard effective score
ReviewIssue recurrence
ChiefEditorNotice
```

## 14.5 验收标准

```text
1. 发布包不能绕过 blocking issue。
2. 平台规则可以来自 MKAOS publish pack。
3. 反馈可以聚类并映射到章节 / 人物 / 节奏 / Issue。
4. 反馈可以触发 weight update 或 RevisionTask。
```

---

# 16. Phase 11：12 章压力测试与 Provider Hard-stop Proof

## 15.1 最小压力测试

必须至少跑通：

```text
12 章长篇链路
第 10 章自动复盘
blocking issue 阻断
revision loop
release package gate
feedback backflow fixture
```

## 15.2 推荐扩展验收

```text
30 章 acceptance test
MKAOS source isolation regression
RAG bucket isolation regression
provider hard-stop proof
cancel / timeout proof
cost ledger proof
rollback rehearsal
```

## 15.3 最终报告

必须输出：

```text
docs/reports/v6-current-state-after-industrialization.md
docs/reports/v6-industrialization-gap-report.md
docs/reports/v6-acceptance-test-report.md
docs/reports/v6-provider-hard-stop-proof.md
docs/reports/v6-rollback-rehearsal-report.md
```

工业化评分建议：

| 维度 | 权重 |
|---|---:|
| OS Envelope 覆盖 | 15% |
| MKAOS 集成深度 | 15% |
| Context Builder 覆盖 | 15% |
| Eval / Issue 阻断能力 | 15% |
| Loop Engineering 可恢复性 | 15% |
| 长篇复盘回写能力 | 10% |
| UI 控制台可维护性 | 5% |
| 发布反馈闭环 | 5% |
| Provider / Cost / Ops 可靠性 | 5% |

---

# 17. Phase 12：最终复盘与工业化差距报告

Phase 12 必须重新完整分析实现状态，输出：

```text
docs/reports/v6-final-current-state.md
docs/reports/v6-final-implementation-matrix.md
docs/reports/v6-final-test-summary.md
docs/reports/v6-industrial-novel-os-gap-analysis.md
docs/reports/v6-next-roadmap-p1-p2.md
```

最终矩阵必须覆盖 MKAOS、OS Envelope、RAG/source isolation、Context Builder、ReviewIssue、Loop Engineering、Longform Recap Agent、Agent Center、UI Editable Console、Publish/Feedback Loop、Provider hard-stop 和 12 章压力测试。

# 18. GitHub 提交计划

建议分支：

```bash
git checkout v6
git pull
git checkout -b feat/v6-post-mkaos-industrialization
```

推荐 commit 顺序：

```text
1. docs: align Novel OS plan with MKAOS audit baseline
2. test: add RAG isolation and source leakage regression coverage
3. feat: standardize OS envelope for MKAOS paths
4. feat: harden MKAOS selector and canon conflict checks
5. feat: route generation flows through context builder
6. feat: unify MKAOS and review issues with blocking gates
7. feat: add loop engineering kernel
8. feat: add longform recap agent
9. feat: add agent center runtime
10. feat: add Novel OS editable consoles
11. feat: add publish gate and feedback loop
12. test: add longform pressure and provider hard-stop proof
13. docs: add final Novel OS v6 industrialization review
```

每个 commit 必须包含：

```text
代码变更
测试
报告
验收命令
风险说明
```

---

# 19. Claude Code 执行约束

Claude Code 必须遵守：

```text
1. 先审计，再设计，再实现，再验收。
2. 不要重做 MKAOS P0。
3. 不要删除已有 passing tests。
4. 不要只加 mock，关键路径必须有真实 proof 或可运行 fixture。
5. 生产写入必须 fail closed。
6. source isolation 和 RAG isolation 不得回退。
7. 所有新路径必须带 project scope 和 lineage。
8. 所有模型调用必须可追踪到 context_bundle_id / knowledge_pack_id / trace_id。
9. 所有 blocking issue 必须能阻断 canonical chapter / release package。
10. 所有阶段必须输出 docs/reports/* 报告。
```

---

# 20. 最终判断

当前 MKAOS P0 **有条件完成**，说明 Novel OS 已经具备了“知识资产底座”的最小闭环，但不能宣称完成全量 MKAOS 或生产级知识操作系统。  
但它还没有完全成为工业化 Novel OS，因为后续仍缺：

```text
RAG/source leakage 专项回归
OS Envelope 全路径强制
MKAOS selector / Canon conflict 加固
Context Builder 统一调度
ReviewIssue 阻断化
Loop Engineering 可恢复执行
长篇复盘 Agent 结构化回写
Agent Center 可观察调度
核心资产 UI 可编辑控制台
发布反馈闭环
真实长篇压力验收
```

因此后续 Claude Code 长任务的核心不应是“继续堆功能”，而应该是：

```text
把 MKAOS 接进 Novel OS 的生产契约；
把上下文、质量、循环、复盘、发布、反馈全部纳入同一套工程治理链路；
让每一次章节生产都可追踪、可审稿、可复盘、可修订、可发布、可回滚。
```
