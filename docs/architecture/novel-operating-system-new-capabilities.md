# Novel Forge / Novel Operating System 新增能力设计文档

## 1. 文档目标

本文档整理 Novel Forge 从“本地 AI 小说生产平台”继续升级为 **Novel Operating System** 所需补充的新功能。

本次新增能力重点不是继续堆写作功能，而是补齐系统级底座：

1. 统一模型调度层；
2. 统一 Prompt 管理；
3. 统一 Workflow；
4. 统一日志 / Trace；
5. Agent 生命周期；
6. 状态同步；
7. 任务恢复；
8. Agent 间通信；
9. L0–L5 分级记忆系统；
10. Tool Gateway / MCP Tool Layer；
11. PostgreSQL + pgvector 知识库检索方案。

这些能力的目标是让系统从：

```text
AI 小说生产平台
```

升级为：

```text
可长期运行、可追踪、可恢复、可扩展的小说生产操作系统
```

---

## 2. 总体架构定位

Novel Operating System 的核心不是“生成正文”，而是统一管理：

```text
模型
Prompt
工具
Agent
Workflow
上下文
知识库
记忆
质量门禁
日志
成本
恢复
反馈
```

推荐总体结构：

```text
User / Web Console / CLI
        ↓
Workflow Engine
        ↓
Agent Runtime / Agent Scheduler
        ↓
Tool Gateway
        ↓
Model Router / Prompt Registry / Knowledge Retriever / Novel KG / Context Builder
        ↓
Artifact System / PostgreSQL / pgvector / Qdrant / MinIO / Local Workspace
        ↓
Trace Ledger / Cost Ledger / Metrics / Recovery
```

---

## 3. 新增能力总览

| 能力 | 是否必须 | 优先级 | 当前定位 |
|---|---|---:|---|
| 统一 Workflow | 必须 | P0 | OS 主干 |
| Agent 生命周期 | 必须 | P0 | 执行单位管理 |
| 任务恢复 | 必须 | P0 | 长链路稳定性 |
| 统一日志 / Trace | 必须 | P0 | 审计与复盘 |
| 状态同步 | 必须 | P0/P1 | 运行一致性 |
| 统一模型调度层 | 必须 | P1 | 模型资源调度器 |
| 统一 Prompt 管理 | 必须 | P1 | PromptOps |
| L0–L5 分级记忆 | 必须 | P1 | 长篇稳定性核心 |
| Tool Gateway / MCP Layer | 必须 | P1 | 统一工具接入 |
| PostgreSQL + pgvector | 建议加入 | P1 | 知识与记忆检索底座 |
| Agent 间通信 | 长期必须 | P2 | 多 Agent 协作能力 |

---

## 4. 统一模型调度层

### 4.1 功能定位

统一模型调度层负责管理所有模型调用。

包括：

```text
ChatGPT
DeepSeek
Claude Code
Codex
Mock Model
本地规则引擎
Embedding Model
```

目标是避免不同模块各自调用模型，导致：

1. 成本无法统计；
2. Prompt 版本无法追踪；
3. 输出格式不一致；
4. 失败无法恢复；
5. 模型质量无法比较；
6. 无法自动 fallback。

### 4.2 推荐模块名

```text
ModelRouter
ModelRuntime
ModelGateway
```

### 4.3 核心能力

```text
ModelProfile
ModelBenchmark
ModelComparison
ModelRoutingPolicy
ProviderRuntimeGuard
ModelCallLog
CostLedger
FallbackPolicy
OutputValidation
```

### 4.4 推荐调用流程

```text
WorkflowNode / Agent
    ↓
ModelRouter.resolve(task_type)
    ↓
PromptRegistry.resolve(prompt_id, version)
    ↓
BudgetPolicy.check()
    ↓
GuardedModelAdapter.call()
    ↓
OutputValidation
    ↓
ModelCallLog
    ↓
CostLedger
    ↓
TraceSpan
```

### 4.5 数据结构建议

```json
{
  "model_route_id": "route_xxx",
  "task_type": "chapter_draft",
  "provider": "deepseek",
  "model_name": "deepseek-chat",
  "fallbacks": [
    {
      "provider": "chatgpt",
      "model_name": "gpt-5.5"
    }
  ],
  "selection_rule": "quality_first|cost_first|latency_first|balanced",
  "max_cost_per_run": 0.5,
  "max_latency_ms": 60000,
  "status": "active"
}
```

---

## 5. 统一 Prompt 管理

### 5.1 功能定位

Prompt 在 Novel OS 中不是临时聊天提示词，而是：

```text
节点执行协议
Agent 行为协议
模型输出 Schema
质量标准入口
上下文组装规则
版本化生产配置
```

没有统一 Prompt 管理，会导致质量波动无法归因。

### 5.2 推荐模块名

```text
PromptRegistry
PromptOps
PromptRuntime
```

### 5.3 核心能力

```text
PromptTemplate
PromptVersion
PromptVariableSchema
PromptRelease
PromptRollback
PromptRegressionReport
PromptBenchmark
PromptNodeBinding
PromptModelCompatibility
```

### 5.4 PromptVersion 结构

```json
{
  "prompt_id": "chapter_draft_prompt",
  "version": "v1.3.0",
  "task_type": "chapter_draft",
  "template": "",
  "variables": {
    "project_memory": "string",
    "chapter_outline": "object",
    "style_profile": "object"
  },
  "output_schema": {},
  "status": "draft|active|deprecated",
  "created_at": "",
  "updated_at": ""
}
```

### 5.5 Prompt 发布流程

```text
创建 PromptVersion
    ↓
绑定 BenchmarkTask
    ↓
运行 PromptRegression
    ↓
质量通过
    ↓
人工确认 / 自动发布
    ↓
设为 active
    ↓
旧版本 deprecated
```

---

## 6. 统一 Workflow

### 6.1 功能定位

Workflow 是 Novel OS 的主干。

没有统一 Workflow，系统只是功能集合：

```text
题材工具 + 大纲工具 + 正文工具 + 审稿工具
```

有统一 Workflow 后，系统才能管理：

```text
节点
依赖
输入
输出
状态
门禁
失败
恢复
重跑
版本
影响传播
```

### 6.2 核心对象

```text
WorkflowDefinition
WorkflowNode
WorkflowEdge
WorkflowRun
NodeRun
ReadyNodeQueue
GateResult
RecoveryPlan
InvalidationReport
```

### 6.3 标准节点结构

```json
{
  "node_id": "node_chapter_draft",
  "node_type": "chapter_draft",
  "name": "章节正文生成",
  "input_schema": {},
  "output_schema": {},
  "processor": "draft.chapter.generate",
  "dependencies": ["node_chapter_plan"],
  "quality_gates": [],
  "retry_policy": {},
  "status": "pending|running|succeeded|failed|blocked"
}
```

### 6.4 推荐主工作流

```text
Project Init
  ↓
Platform Strategy
  ↓
Topic Selection
  ↓
Worldbuilding
  ↓
Character Design
  ↓
Long Outline
  ↓
Volume Outline
  ↓
Chapter Plan
  ↓
Memory Select
  ↓
Context Build
  ↓
Chapter Draft
  ↓
Review
  ↓
Revision
  ↓
Continuity Update
  ↓
Feedback Analysis
```

---

## 7. 统一日志 / Trace

### 7.1 功能定位

统一日志不是简单保存运行日志，而是让系统可以回答：

```text
这一章是怎么生成出来的？
用了哪些上下文？
哪个模型生成的？
哪个 Agent 执行的？
经过了哪些门禁？
哪里失败过？
花了多少钱？
哪个节点改动影响了后续章节？
```

### 7.2 核心对象

```text
TraceSpan
WorkflowRun
NodeRun
AgentRun
AgentEvent
ToolInvocation
ModelCallLog
CostLedger
GateResult
RecoveryRecord
```

### 7.3 TraceSpan 结构

```json
{
  "trace_id": "trace_xxx",
  "span_id": "span_xxx",
  "parent_span_id": "",
  "span_type": "workflow|node|agent|tool|model|gate|cost",
  "name": "",
  "status": "running|succeeded|failed",
  "started_at": "",
  "finished_at": "",
  "attributes": {}
}
```

### 7.4 前端页面建议

```text
Trace Timeline
Workflow Runtime Console
Agent Timeline
Cost Dashboard
Gate Result Viewer
Failure Recovery Viewer
```

---

## 8. Agent 生命周期

### 8.1 功能定位

Agent 是 Novel OS 的执行单位。系统必须知道每个 Agent：

```text
为什么运行
输入是什么
输出是什么
当前状态是什么
是否失败
能否恢复
是否超预算
是否需要人工确认
```

### 8.2 推荐状态机

```text
planned
prepared
running
checkpointed
waiting_human
verifying
succeeded
needs_revision
failed
dead_letter
recovered
cancelled
```

### 8.3 核心对象

```text
AgentContract
AgentRun
AgentEvent
AgentCheckpoint
AgentBudget
AgentGate
AgentMetric
AgentFailureReport
AgentSlaReport
AgentRollbackReport
```

### 8.4 AgentRun 结构

```json
{
  "agent_run_id": "agent_run_xxx",
  "agent_type": "draft_agent",
  "operation": "generate_chapter",
  "status": "running",
  "input_assets": [],
  "output_assets": [],
  "model_provider": "",
  "model_name": "",
  "prompt_version": "",
  "token_budget": 0,
  "token_used": 0,
  "cost_estimate": 0,
  "checkpoint": {},
  "trace": {},
  "human_gate": {},
  "retry_count": 0
}
```

---

## 9. 状态同步

### 9.1 功能定位

状态同步保证：

```text
Workflow
Agent
Queue
Task
UI
Trace
Cost
```

对同一任务的状态认知一致。

### 9.2 风险场景

没有状态同步会出现：

```text
任务已经失败，UI 还显示 running
Agent 已经完成，Workflow 没有继续
Queue 已经 dead_letter，项目工作台不知道
人工审批完成后任务无法恢复
```

### 9.3 建议新增 StateBus

```text
StateBus
StateEvent
StateSnapshot
StateReplay
StateConflictDetector
```

### 9.4 StateEvent 结构

```json
{
  "event_id": "state_event_xxx",
  "source_type": "workflow|agent|queue|task|tool",
  "source_id": "",
  "from_status": "",
  "to_status": "",
  "event_type": "",
  "reason": "",
  "trace_id": "",
  "created_at": ""
}
```

---

## 10. 任务恢复

### 10.1 功能定位

小说生产是长链路任务，必须支持恢复。

典型失败包括：

```text
模型输出格式错误
上下文过长
审稿失败
Agent 超时
成本超预算
人工审批暂停
工具调用失败
正文生成失败
```

### 10.2 必备能力

```text
pause
resume
retry
checkpoint
dead_letter
failure_report
recovery_instruction
rollback
quarantine
continue_from_node
```

### 10.3 推荐恢复流程

```text
任务失败
  ↓
记录 FailureReport
  ↓
写入 TraceSpan
  ↓
进入 dead_letter 或 waiting_human
  ↓
生成 RecoveryPlan
  ↓
人工 / 自动恢复
  ↓
从 checkpoint 或指定 node 继续
```

---

## 11. Agent 间通信

### 11.1 功能定位

早期系统可以通过 Workflow + Artifact 间接协作。

但完整 Novel OS 后期需要 Agent 间通信，例如：

```text
Review Agent 将问题交给 Draft Agent
Continuity Agent 阻止 Draft Agent 继续生成
Chief Editor Agent 协调多个 Agent
Feedback Agent 通知 Outline Agent 调整后续细纲
Model Evaluation Agent 建议 Draft Agent 换模型
```

### 11.2 建议新增对象

```text
AgentMessage
AgentInbox
AgentOutbox
AgentHandoff
MessageAck
MessageReplay
AgentConversationTrace
```

### 11.3 AgentMessage 结构

```json
{
  "message_id": "msg_xxx",
  "from_agent": "review_agent",
  "to_agent": "draft_agent",
  "message_type": "revision_request",
  "payload": {},
  "related_artifact_ids": [],
  "status": "sent|received|acked|failed|replayed",
  "trace_id": "",
  "created_at": ""
}
```

### 11.4 优先级

Agent 间通信属于 P2。

MVP 阶段可以先使用：

```text
Workflow
Artifact
AgentEvent
DispatchQueue
```

间接替代。

---

## 12. L0–L5 分级记忆系统

### 12.1 功能定位

分级记忆系统解决的是：

```text
长篇小说到底应该记住什么？
生成当前章节时，哪些记忆应该进入上下文？
哪些记忆只进入知识图谱？
哪些记忆用于审稿？
哪些记忆用于质量改进？
```

### 12.2 推荐命名

```text
Long-form Memory System
长篇小说分级记忆系统
```

### 12.3 记忆层级

| 层级 | 名称 | 内容 |
|---|---|---|
| L0 | 系统级记忆 | 平台规则、通用模板、模型经验、精品标准 |
| L1 | 项目级记忆 | 题材、主题、世界观、核心卖点 |
| L2 | 卷级记忆 | 每一卷目标、冲突、阶段性成长 |
| L3 | 章节级记忆 | 当前章细纲、前后章摘要 |
| L4 | 实体级记忆 | 人物、势力、地点、物品、功法、伏笔 |
| L5 | 质量级记忆 | 常见问题、风格偏差、审稿结论 |

### 12.4 MemoryRecord 结构

```json
{
  "memory_id": "mem_xxx",
  "project_id": "project_xxx",
  "level": "L0|L1|L2|L3|L4|L5",
  "memory_type": "system|project|volume|chapter|entity|quality",
  "title": "",
  "summary": "",
  "content": {},
  "source_artifact_ids": [],
  "related_entity_ids": [],
  "related_chapters": [],
  "priority": 0,
  "stability": "stable|evolving|volatile",
  "status": "active|stale|deprecated",
  "last_verified_at": "",
  "created_at": "",
  "updated_at": ""
}
```

### 12.5 Memory Selector

必须新增：

```text
MemorySelector
```

它负责根据当前 WorkflowNode 自动选择记忆。

例如：

| 节点 | 记忆选择 |
|---|---|
| 题材生成 | L0 + L1 |
| 世界观生成 | L0 + L1 + L4 |
| 卷纲生成 | L1 + L2 + L4 |
| 章节细纲 | L1摘要 + L2 + L3 + L4 |
| 正文生成 | L1摘要 + L2摘要 + L3强 + L4相关 + L5短 |
| 审稿 | L1 + L2 + L3 + L4 + L5 |
| 修订 | L3 + L4 + L5 |
| 反馈分析 | L1 + L2 + L5 |

### 12.6 接入流程

```text
项目创建
  ↓
生成 L1 项目记忆
  ↓
生成大纲 / 卷纲
  ↓
生成 L2 卷级记忆
  ↓
生成章节细纲
  ↓
生成 L3 章节记忆
  ↓
同步 L4 实体记忆
  ↓
正文生成
  ↓
审稿
  ↓
提取 L5 质量记忆
  ↓
修订
  ↓
刷新 L3 / L4 / L5
```

---

## 13. Tool Gateway / MCP Tool Layer

### 13.1 功能定位

系统需要统一工具接入层，但不应只叫 MCP Tool Layer。

推荐命名：

```text
Tool Gateway
Tool Runtime Layer
统一工具接入层
```

MCP 只是其中一种外部工具适配协议。

### 13.2 目标

统一管理：

```text
工具注册
工具发现
工具权限
工具调用
输入输出校验
调用日志
Trace
成本
超时
重试
失败恢复
Agent 工具边界
```

### 13.3 推荐架构

```text
Agent / Workflow
  ↓
Tool Gateway
  ↓
Tool Registry
  ↓
Permission / Budget / Trace / Gate
  ↓
Local Tool Adapter / MCP Adapter / Model Adapter / DB Adapter
  ↓
具体工具执行
```

### 13.4 核心对象

```text
ToolDefinition
ToolAdapter
ToolInvocation
ToolPermissionPolicy
MCPServerRegistry
```

### 13.5 ToolDefinition

```json
{
  "tool_id": "tool_xxx",
  "name": "novel_kg.query_impact",
  "tool_type": "local|mcp|model|database|vector|graph|storage|review|publishing",
  "description": "",
  "input_schema": {},
  "output_schema": {},
  "permission_scope": [],
  "risk_level": "low|medium|high|critical",
  "timeout_ms": 30000,
  "cost_policy": {},
  "status": "active|disabled|deprecated"
}
```

### 13.6 ToolInvocation

```json
{
  "invocation_id": "tool_call_xxx",
  "tool_id": "novel_kg.query_impact",
  "agent_run_id": "",
  "workflow_run_id": "",
  "node_run_id": "",
  "trace_id": "",
  "input_hash": "",
  "input_summary": "",
  "output_summary": "",
  "status": "succeeded|failed|blocked|timeout|retry_scheduled",
  "latency_ms": 0,
  "cost_estimate": 0,
  "error": "",
  "created_at": ""
}
```

### 13.7 接入顺序

#### 第一阶段：统一内部工具

```text
novel_kg.query
novel_kg.impact
novel_kg.conflicts
context_builder.build_bundle
workflow.execute
workflow.resume
agent_scheduler.tick
review.run
revision.apply_patch
trace.timeline
cost.create_dashboard
```

#### 第二阶段：统一模型工具

```text
model.generate
model.review
model.revise
model.analyze
embedding.search
```

#### 第三阶段：接入 MCP

```text
mcp.discover_tools
mcp.invoke_tool
mcp.read_resource
mcp.get_prompt
```

#### 第四阶段：安全治理

```text
Tool Risk Level
Human Approval Gate
Prompt Injection Guard
Output Sanitizer
Capability Attestation
Tool Allowlist
Tool Audit Report
```

---

## 14. PostgreSQL + pgvector 知识库方案

### 14.1 功能定位

PostgreSQL + pgvector 用于增强 AI 检索能力，尤其适合：

```text
资产检索
知识库检索
分级记忆检索
审稿历史检索
实体状态检索
Context Builder 候选召回
```

不建议直接替代 Qdrant。

推荐定位：

```text
PostgreSQL + pgvector = OS 内部统一知识 / 记忆检索底座
Qdrant = 可选高性能向量服务
```

### 14.2 适用场景

| 场景 | 推荐 |
|---|---|
| 项目内记忆检索 | PostgreSQL + pgvector |
| L0–L5 分级记忆 | PostgreSQL + pgvector |
| 审稿历史问题检索 | PostgreSQL + pgvector |
| 资产元数据 + 向量混合检索 | PostgreSQL + pgvector |
| 多项目中小规模知识库 | PostgreSQL + pgvector |
| 海量素材向量库 | Qdrant |
| 高并发向量检索服务 | Qdrant |

### 14.3 推荐新增表

#### memory_chunks

```sql
CREATE TABLE memory_chunks (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    book_id TEXT,
    memory_level TEXT,
    memory_type TEXT,
    volume_no INTEGER,
    chapter_no INTEGER,
    entity_id TEXT,
    entity_type TEXT,
    title TEXT,
    summary TEXT,
    content_jsonb JSONB,
    source_artifact_id TEXT,
    status TEXT,
    priority INTEGER,
    quality_score NUMERIC,
    embedding VECTOR,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

#### knowledge_chunks

```sql
CREATE TABLE knowledge_chunks (
    id TEXT PRIMARY KEY,
    source_id TEXT,
    source_type TEXT,
    domain TEXT,
    title TEXT,
    chunk_text TEXT,
    chunk_summary TEXT,
    tags TEXT[],
    metadata_jsonb JSONB,
    embedding VECTOR,
    quality_score NUMERIC,
    copyright_status TEXT,
    created_at TIMESTAMP
);
```

#### artifact_embeddings

```sql
CREATE TABLE artifact_embeddings (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    artifact_id TEXT,
    artifact_type TEXT,
    artifact_path TEXT,
    version TEXT,
    text_hash TEXT,
    embedding_model TEXT,
    embedding VECTOR,
    metadata_jsonb JSONB,
    created_at TIMESTAMP
);
```

#### review_memory_chunks

```sql
CREATE TABLE review_memory_chunks (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    issue_type TEXT,
    severity TEXT,
    chapter_no INTEGER,
    problem_text TEXT,
    review_conclusion TEXT,
    revision_strategy TEXT,
    embedding VECTOR,
    status TEXT,
    created_at TIMESTAMP
);
```

#### entity_memory_chunks

```sql
CREATE TABLE entity_memory_chunks (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    entity_id TEXT,
    entity_type TEXT,
    entity_name TEXT,
    state_summary TEXT,
    relationship_summary TEXT,
    chapter_range TEXT,
    embedding VECTOR,
    metadata_jsonb JSONB,
    updated_at TIMESTAMP
);
```

### 14.4 推荐新增服务

```text
PgVectorStore
EmbeddingJob
Chunker
HybridRetriever
MemoryRetriever
KnowledgeRetriever
ReviewMemoryRetriever
EntityMemoryRetriever
ContextCandidateRanker
```

### 14.5 接入 Context Builder

Context Builder 增加参数：

```text
retrieval_backend = local_json | qdrant | pgvector | hybrid
```

推荐流程：

```text
WorkflowNode 声明检索需求
  ↓
MemorySelector 选择 L0–L5 记忆
  ↓
HybridRetriever 检索候选
  ↓
ContextCandidateRanker 排序
  ↓
Context Builder 打包上下文
  ↓
Agent / Model 执行
```

---

## 15. 新增模块优先级

### P0：已有能力继续验收

```text
统一 Workflow
Agent 生命周期
任务恢复
统一日志 / Trace
状态同步基础
```

目标是确保现有 OS Runtime 稳定。

### P1：下一阶段重点新增

```text
ModelRouter
PromptRegistry
Tool Gateway
L0–L5 分级记忆
PostgreSQL + pgvector 检索层
Memory Selector
Hybrid Retriever
```

### P2：高级协作能力

```text
AgentMessageBus
Agent Inbox / Outbox
MCP 深度接入
Tool Security Gateway
StateBus
Observability UI
Prompt A/B Testing
Model Auto Fallback
```

---

## 16. 推荐实施顺序

### 第一阶段：统一运行入口

```text
Tool Gateway
ModelRouter
PromptRegistry
```

目标：

```text
所有 Agent / Workflow 节点不再直接调用模型和工具。
```

### 第二阶段：分级记忆与检索

```text
L0–L5 MemoryRecord
MemorySelector
PgVectorStore
HybridRetriever
Context Builder 接入
```

目标：

```text
系统能根据节点自动选择记忆和知识上下文。
```

### 第三阶段：运行审计增强

```text
ToolInvocation
Trace Timeline
Cost Dashboard
StateEvent
RecoveryPlan
```

目标：

```text
所有工具、模型、Agent、Workflow 调用都可追踪、可恢复、可归因。
```

### 第四阶段：Agent 协作增强

```text
AgentMessage
AgentInbox
AgentOutbox
AgentHandoff
MessageAck
MessageReplay
```

目标：

```text
多 Agent 可以围绕正文、审稿、连续性、反馈进行协作。
```

---

## 17. Codex / Claude Code 实现提示词

```text
你是 novel-forge 的后端架构工程师。

目标：
根据 Novel Operating System 的最新设计，为项目补充以下 P1/P2 能力：
1. Tool Gateway 统一工具接入层；
2. ModelRouter 统一模型调度层；
3. PromptRegistry 统一 Prompt 管理；
4. L0-L5 Long-form Memory System；
5. PostgreSQL + pgvector 知识库检索层；
6. MemorySelector + HybridRetriever；
7. ToolInvocation / StateEvent / AgentMessageBus 的基础资产和 API。

要求：
1. 不破坏现有 Workflow Engine、Agent Scheduler、Runtime Ledger、Novel KG、Context Builder。
2. 所有新增能力必须以 Artifact / Asset / Run / Trace 的方式接入现有系统。
3. 所有 Agent 调用工具必须经过 Tool Gateway。
4. 所有模型调用必须逐步迁移到 ModelRouter。
5. 所有 Prompt 必须通过 PromptRegistry 获取版本。
6. L0-L5 记忆必须能被 Context Builder 按节点类型自动选择。
7. pgvector 是新增检索后端，不删除 Qdrant。
8. Context Builder 增加 retrieval_backend：local_json / qdrant / pgvector / hybrid。
9. 所有工具调用写入 ToolInvocation 和 TraceSpan。
10. 所有模型调用写入 ModelCallLog 和 CostLedger。
11. 增加必要的数据模型、service、API、测试和文档。
12. 每一轮修改后运行测试，若测试失败，优先修复。
13. 更新 README、ARCHITECTURE、WORKFLOW、TESTING、AGENTS、CLAUDE 文档。
```

---

## 18. 最终判断

本次新增能力对 Novel Forge 的意义如下：

| 新功能 | 对系统价值 |
|---|---|
| 统一模型调度层 | 控制模型质量、成本、fallback |
| 统一 Prompt 管理 | 控制 Prompt 版本、回归、发布 |
| 统一 Workflow | 控制生产流程 |
| 统一日志 / Trace | 支持审计、复盘、调试 |
| Agent 生命周期 | 管理执行单元 |
| 状态同步 | 保证运行一致性 |
| 任务恢复 | 支持长链路稳定生产 |
| Agent 间通信 | 支持高级多 Agent 协作 |
| L0–L5 分级记忆 | 支持百万字长篇稳定性 |
| Tool Gateway / MCP Layer | 统一工具接入与权限 |
| PostgreSQL + pgvector | 提升知识库和记忆检索能力 |

最终目标：

```text
Novel Forge 不只是能生成小说，
而是能像操作系统一样统一调度模型、Prompt、工具、Agent、Workflow、知识、记忆、质量、日志、成本和反馈。
```
