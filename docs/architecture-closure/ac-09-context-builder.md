# AC-09 Context Builder

状态：`PLANNED`  
阶段：Phase 2 / Novel Domain Closure  
前置依赖：AC-06、AC-07、AC-08、AC-10 的契约

## 1. ADR

### 背景

Context Builder 是计划、Canon、StoryState、MKAOS、Source、Prompt 和 Provider 之间的核心编译层。若 Draft、Review、Revision、Judge、Recap 等模块各自拼接 Prompt，后续无法证明实际发送内容、来源隔离、Token 预算、状态一致性和长篇上下文增长。

### 决策

所有正式模型任务必须通过统一 Context Builder。Context Builder 输入冻结具体 AssetVersion、StoryState Snapshot、KnowledgePack、StageProfile、Source Policy、Token Budget 和 Provider Capability；输出不可变 ContextManifest 与 ActualSentContext。

优先级固定为：

```text
Authority Constraints
> Canon
> Current StoryState
> Active Plan
> Approved Book Design Assets
> Required KnowledgePack
> Recent Chapter Context
> Historical Summary
> Optional Material
```

任何裁剪、压缩、冲突和拒绝都必须留下证据。

## 2. 核心契约

### 输入

```text
ExecutionTarget
StageProfileVersion
FrozenAssetVersions
CanonSnapshotVersion
StoryStateSnapshotVersion
KnowledgePackVersions
SourcePolicyVersion
TokenBudget
ProviderCapabilitySnapshot
PromptPolicyVersion
```

### 输出

```text
ContextManifest
ActualSentContext reference and digest
SelectedItems
RejectedItems with reasons
CompressionEvidence
ConflictEvidence
SourceEligibilityEvidence
TokenEstimate and actual usage link
LeakageEvidence
```

### StageProfile

必须至少覆盖 Book Design、Book/Volume/Arc/Group/Chapter Plan、Draft、Review、Revision、Canon Extraction、Quality Judge、Reader Outcome、Longform Recap 和 Publishing copy。

## 3. 实施范围

- 建立统一 selector、resolver、priority、budget 和 compiler；
- 区分 deterministic context assembly 与 model-based compression；
- ContextManifest 绑定 Operation/Attempt/RouteSnapshot；
- ActualSentContext 在调用前生成并冻结；
- Provider 返回 usage 后关联实际 token/cost；
- 建立 source leakage、raw sample leakage、cross-book contamination gate；
- 建立长篇历史摘要层：recent window、chapter group summary、arc summary、volume summary；
- 禁止运行时隐式重建索引改变 selection 结果。

## 4. 代码位置

### 当前重点

- `src/novel_forge/modules/context_builder/`
- `src/novel_forge/modules/production_execution/`
- `src/novel_forge/modules/chapter_authority/handlers.py`
- MKAOS selector/pack modules
- Canon/StoryState/longform modules
- RAG、pgvector、Qdrant/local index modules
- Provider InputManifest/PromptBundle/ActualSentContext 相关契约

### 目标位置

- `src/novel_forge/modules/context_authority/contracts.py`
- `.../stage_profiles.py`
- `.../selectors.py`
- `.../budget.py`
- `.../compression.py`
- `.../compiler.py`
- `.../leakage.py`
- `.../repositories.py`
- `tests/integration/test_context_manifest_postgres.py`

若现有 Context Builder 已承担这些职责，应加固并权威化，不新建平行拼接器。

### 禁止位置

- Handler 直接拼接大段 prompt；
- Provider adapter 自行加载 Canon/MKAOS；
- Agent 在 Scope 外动态搜索并加入上下文；
- 只保存模板而不保存 ActualSentContext；
- Context 超限后静默截断；
- production 中用当前最新 Asset 代替冻结 version。

## 5. 迁移脚本设计

数据库需支持 StageProfile versions、ContextManifest、selected/rejected items、compression evidence、actual context object reference、token budget、source/leakage evidence 和 operation binding。

脚本：

```text
scripts/migrations/inventory_prompt_assembly_paths.py
scripts/migrations/import_context_profiles.py
scripts/migrations/backfill_context_manifests.py
scripts/migrations/link_actual_sent_context.py
scripts/migrations/report_unverifiable_model_inputs.py
scripts/migrations/quarantine_cross_book_context.py
```

历史调用若无法恢复 ActualSentContext，只能标记 `input_reproducibility=false`，不得伪造。

## 6. 实施计划

1. 枚举所有模型调用和当前 prompt assembly 路径。
2. 固定 StageProfile、ContextItem 和 Manifest contract。
3. 接入 Planning、Canon、StoryState、MKAOS 和 Source Authority。
4. 实现 deterministic selection、priority 和 token budget。
5. 实现分层摘要与可选 governed compression Operation。
6. 将所有 Gateway model capability 强制要求 ContextManifest。
7. 移除/阻止直接 prompt 拼接路径。
8. 完成单章、L10、跨书和 leakage 证明。

## 7. 测试矩阵

| 测试 | 场景 | 通过条件 |
|---|---|---|
| Determinism | 相同版本与预算 | Manifest/digest 一致 |
| Priority | 超预算 | 按固定优先级裁剪 |
| Required item | Canon/Plan 被裁剪 | 构建失败，不静默继续 |
| Frozen version | 上游出现新版本 | 已 admitted Attempt 输入不变化 |
| Leakage | evidence-only source | 不进入 ActualSentContext |
| Cross-book | 相似角色/知识 | 不读取其他 Book 私有资产 |
| Compression | model compression | 独立 Operation、输入输出留证 |
| Token | estimate 与 provider usage | 可对账并记录偏差 |
| Replay | 根据 Manifest 重建 | digest 一致 |
| Long chain | 10/30 章 | context size 受控、关键信息保留 |

## 8. Acceptance Gate

```text
all_production_model_calls_context_bound=true
stage_profile_registry_complete=true
actual_sent_context_persisted=true
context_version_freeze_verified=true
source_leakage_gate_verified=true
cross_book_context_isolation_verified=true
token_budget_fail_closed=true
l10_context_growth_verified=true
```

## 9. 风险

- ActualSentContext 存储成本：正文可放 Object Store，PostgreSQL 保存 digest、manifest 和引用。
- 压缩模型引入新不确定性：压缩也必须是 Operation/Attempt，不允许隐藏调用。
- 规则过于僵硬影响创作：StageProfile 可版本化，但 Authority/Canon/Source 边界不可降级。
- RAG 可重现性差：冻结索引 checkpoint、embedding profile、query 和 selected version。