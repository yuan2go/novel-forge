# AC-10 Source 与 MKAOS Authority

状态：`PLANNED`  
阶段：Phase 2 / Novel Domain Closure  
前置依赖：AC-03、AC-04、AC-06

## 1. ADR

### 背景

外部来源、素材、中间清洗结果、知识卡、创作规则、模板和生产 KnowledgePack 当前分布在 Source Intake、MKAOS、Materials、Analysis、RAG 和 LocalStorage 路径。若生产任务动态查询当前知识库，无法重现当时使用了哪些来源、版本、授权与规则。

### 决策

Source Authority 与 MKAOS Authority 分离：

- Source Authority 拥有原始来源、文档快照、许可、风险、资格、隔离、刷新与保留；
- MKAOS Authority 拥有从合格来源形成的 KnowledgeCard、Rule、Template、Graph、KnowledgePack、Usage、Feedback 和 Weight；
- Material 是可供创作选择的内容素材；Knowledge 是指导生成、规划、审稿和决策的方法资产；
- 正式生产只引用冻结的 SourceSnapshot 和 KnowledgePack Version，不动态消费“当前最新库”。

MKAOS 不能直接修改 Canon、Plan 或 Draft；它只能提供版本化生产输入和建议。

## 2. 生产链

```text
Source Registration
→ Snapshot
→ License/Risk/Eligibility
→ Extraction Operation
→ Knowledge Candidate
→ Review/Approval
→ Knowledge Asset Version
→ KnowledgePack Build
→ Context Selection
→ Usage Evidence
→ Quality Feedback
→ Governed Weight Proposal
```

高风险、版权受限、evidence-only 或 quarantined 来源不得进入生成上下文。

## 3. 实施范围

### Source Authority

- Source、Document、Snapshot、connector identity；
- content digest、origin、license、retention；
- R0-R4 eligibility；
- quarantine、stale、refresh、diff；
- connector effect/receipt；
- source-to-derived-asset lineage。

### MKAOS Authority

- Knowledge type registry；
- immutable KnowledgeCard/Rule/Template versions；
- review、approval、activation；
- KnowledgePack composition manifest；
- selector policy version；
- usage and feedback evidence；
- weight adjustment proposal，不允许自动无审计学习。

## 4. 代码位置

### 当前重点

- `src/novel_forge/modules/source_intake/`
- `src/novel_forge/modules/source_authority/`（由 AC-00 验证）
- `src/novel_forge/modules/mkaos/`
- `src/novel_forge/modules/mkaos_ingestion/`
- `src/novel_forge/modules/mkaos_quality/`
- `src/novel_forge/modules/mkaos_lineage/`
- `src/novel_forge/modules/mkaos_authority/`（由 AC-00 验证）
- Materials、Analysis、Context Builder、pgvector/Qdrant modules

### 目标收敛

- `src/novel_forge/modules/source_authority/contracts.py`
- `.../application.py`、`connectors.py`、`eligibility.py`、`repositories.py`
- `src/novel_forge/modules/mkaos_authority/contracts.py`
- `.../knowledge_assets.py`、`packs.py`、`selection.py`、`usage.py`、`feedback.py`
- `tests/integration/test_source_mkaos_authority_postgres.py`

不得在 Context Builder 内重新实现 Source eligibility 或 MKAOS approval。

## 5. 迁移脚本设计

数据库 migration 需核验或建立 Source roots/snapshots/eligibility、Knowledge assets/versions、pack manifests、lineage、usage、feedback 和 governed weight proposals。

脚本：

```text
scripts/migrations/inventory_sources_and_knowledge.py
scripts/migrations/import_source_snapshots.py
scripts/migrations/recompute_source_eligibility.py
scripts/migrations/import_knowledge_assets.py
scripts/migrations/build_knowledge_lineage.py
scripts/migrations/build_knowledge_pack_manifests.py
scripts/migrations/quarantine_unlicensed_or_untraceable_assets.py
```

来源、许可或 lineage 不可解释的知识不得自动激活，只能 quarantine/evidence-only。

## 6. 实施计划

1. 固定 Source、Eligibility、KnowledgeAsset、KnowledgePack contract。
2. 修复/验证 Source 和 MKAOS Authority 模块与 migrations。
3. 将 connector 调用迁入 Production Execution Plane。
4. 迁移生产会使用的来源和知识，不先迁全部历史语料。
5. 建立 Pack Builder、selection manifest 和 usage evidence。
6. 接入 Context Builder 的冻结输入。
7. 建立 feedback→weight proposal→review 流程。
8. 冻结 Legacy 生产 writer，保留导入/缓存路径。

## 7. 测试矩阵

| 测试 | 场景 | 通过条件 |
|---|---|---|
| Source digest | 内容变化 | 生成新 Snapshot，不覆盖旧版 |
| Eligibility | quarantined/evidence-only | 不进入生成上下文 |
| License expiry | 已激活 Pack 来源过期 | Pack 标记 stale，生产 gate 按策略阻塞 |
| Lineage | Knowledge 无 Source | 激活失败 |
| Pack freeze | 知识库后来更新 | 已 admitted Operation 使用旧 Pack version |
| Selector determinism | 相同 scope/profile | selection manifest 一致 |
| Cross-book/private | Book 私有材料 | 不泄漏到其他 Book |
| Usage | Context 实际采用 | 记录具体 knowledge version |
| Feedback | 质量下降 | 只生成 weight proposal，不自动修改权重 |
| Connector UNKNOWN | 外部抓取超时 | 进入 Effect reconciliation |

## 8. Acceptance Gate

```text
source_authority_single_writer=true
mkaos_authority_single_writer=true
source_eligibility_fail_closed=true
knowledge_lineage_complete=true
production_knowledge_pack_version_frozen=true
context_selection_manifested=true
usage_feedback_governed=true
untraceable_knowledge_active_zero=true
```

## 9. 风险

- 全量语料迁移周期过长：只迁生产关键集合，其余按需求导入。
- Source 与 Knowledge 混淆：Source 负责来源事实，MKAOS 负责经治理的知识资产。
- 自动学习污染规则：反馈只形成 Proposal，需回归集和 Authority approval。
- 向量索引不一致：索引是投影，Pack manifest 和版本引用才是正式证据。