# AC-06 统一资产版本模型

状态：`PLANNED`  
阶段：Phase 1 / Shared Kernel Closure  
前置依赖：AC-03、AC-05

## 1. ADR

### 背景

Novel OS 的核心对象不是普通可变 CRUD 记录，而是持续演化、需要审核、激活、回滚、依赖分析和重规划的创作资产。若 BookDesign、Plan、Draft、Canon、StoryState、KnowledgePack、QualityReport 分别实现自己的 `version/current/approved/active/history` 字段，后续影响分析、回滚和 Agent 决策会形成大量重复逻辑。

### 决策

所有核心内容与治理对象统一建模为：

```text
Asset
AssetVersion
AssetDependency
AssetSnapshot
AssetEvidence
AssetDecision
AssetActivation
AssetSupersession
```

Asset 表示逻辑身份；AssetVersion 表示不可变内容版本。Version 一旦提交不可原地修改。审批、激活和 supersede 是独立记录，不通过覆盖内容表达。

统一生命周期：

```text
PROPOSED
→ VALIDATED
→ REVIEW_PENDING
→ APPROVED
→ ACTIVE
→ SUPERSEDED
→ ARCHIVED
```

领域可使用子集，但状态语义不得重新定义。

## 2. 核心契约

### Asset

至少包含：`asset_id`、`asset_type`、project/workspace/book scope、logical_key、owner_context、created_at。

### AssetVersion

至少包含：

- version_id；
- asset_id；
- version_no；
- schema_version；
- immutable content digest；
- object/content reference；
- input manifest；
- producer Operation/Attempt；
- created_by；
- status；
- validation evidence。

### Dependency

依赖必须引用具体 version，而不是逻辑 Asset：

```text
ChapterPlan v4
→ ArcPlan v2
→ CharacterState v17
→ CanonSnapshot v20
```

Dependency 类型至少区分：required、derived_from、constrained_by、evaluates、supersedes、effective_after。

### Decision 与 Activation

批准不等于立即生效。激活记录必须支持：

- effective_from_chapter；
- effective_until；
- target scope；
- activation reason；
- previous active version；
- Authority Decision；
- rollback/compensation reference。

## 3. 实施范围

1. 建立统一 Asset Registry 和 type schema registry。
2. 识别现有独立 version 模型并映射到统一语义。
3. 为核心资产建立 immutable insert、dependency、decision、activation API。
4. 建立 active-version resolver，禁止业务表中的 mutable `current=true` 成为唯一事实。
5. 建立 impact traversal 和 stale/superseded projection。
6. 建立大型内容的 Object Store manifest。
7. 将历史、回滚和人工修正表达为新版本与 Decision，而非原地修改。

## 4. 代码位置

### 当前重点

- 现有 schema/asset registry；
- `src/novel_forge/storage/authority_repositories.py`
- Chapter Authority 中的 Draft、Canon、Quality、Export version；
- Book Authority 的 frozen inputs；
- MKAOS、Context Builder、ReviewIssue、Publishing 的版本对象；
- `src/novel_forge/storage/migrations/versions/`

### 目标新增或收敛

- `src/novel_forge/modules/asset_authority/contracts.py`
- `.../registry.py`
- `.../application.py`
- `.../repositories.py`
- `.../activation.py`
- `.../impact.py`
- `.../snapshots.py`
- `tests/contract/test_asset_version_contract.py`
- `tests/integration/test_asset_authority_postgres.py`

若已有通用 AssetVersion 实现，优先扩展和收敛，禁止创建平行 asset authority。

### 禁止位置

- Domain 中原地更新已批准内容；
- 每个模块自建 `version` 和 `active` 语义；
- dependency 只引用 asset_id 不引用 version_id；
- 通过文件名判断当前版本；
- 删除旧版本实现“回滚”。

## 5. 迁移脚本设计

数据库 migration 应评估并补齐：

- `assets`；
- `asset_versions`；
- `asset_dependencies`；
- `asset_decisions`；
- `asset_activations`；
- `asset_supersessions`；
- `asset_evidence_links`；
- type/schema/version unique constraints；
- scope consistency constraints。

数据脚本：

```text
scripts/migrations/inventory_versioned_entities.py
scripts/migrations/map_legacy_assets_to_registry.py
scripts/migrations/import_asset_versions.py
scripts/migrations/build_asset_dependencies.py
scripts/migrations/verify_asset_content_digests.py
scripts/migrations/resolve_active_version_conflicts.py
scripts/migrations/quarantine_mutable_history.py
```

遇到同一逻辑资产多个 active 版本时不得自动选择，生成冲突报告并进入 Authority review。

## 6. 实施计划

1. 形成全量资产类型目录和 Owner Context。
2. 定义 Asset/Version/Dependency/Decision/Activation contract。
3. 选择现有 AssetVersion 实现作为唯一内核并加固约束。
4. 先迁移 BookDesign、Plan、ChapterPlan、Draft、CanonSnapshot、StoryStateSnapshot、QualityEvidence。
5. 再迁移 MKAOS、Source、Context、Publishing 和 Feedback 资产。
6. 为 active resolver、impact graph 和 rollback 建立应用服务。
7. 冻结旧 mutable writer。
8. 将所有生产输入改为具体 version references。

## 7. 测试矩阵

| 测试 | 场景 | 通过条件 |
|---|---|---|
| Immutability | 修改已存在 version content | DB/应用拒绝 |
| Version monotonic | 并发创建下一版本 | version_no 唯一 |
| Digest | content 与 digest 不一致 | commit 拒绝 |
| Dependency scope | Book A version 依赖 Book B 私有资产 | 拒绝 |
| Activation | 已批准但未来生效 | 当前 resolver 不提前激活 |
| Multiple active | 同 scope 同时激活两个版本 | 冲突阻止 |
| Supersession | 新版本替代旧版本 | 历史保留、resolver 正确 |
| Impact | 上游版本变化 | 下游 stale/impact 可追踪 |
| Rollback | 恢复旧内容 | 创建新 activation/decision，不删历史 |
| Object content | object digest 不匹配 | 版本不可提交 |
| Legacy import | 重复导入 | idempotent |

## 8. Acceptance Gate

```text
unified_asset_registry_active=true
core_assets_use_immutable_versions=true
asset_dependencies_version_bound=true
approval_activation_separated=true
active_version_conflicts_blocked=true
impact_analysis_available=true
rollback_preserves_history=true
parallel_version_semantics_zero=true
```

## 9. 风险与控制

- 所有对象都资产化导致复杂：只对需要版本、审批、追踪或重放的正式对象强制。
- 依赖图过大：使用类型化边和增量 projection，不在事务内全图遍历。
- 迁移旧 mutable history 无法还原：保留 source digest 和 conversion evidence，无法解释的记录 quarantine。
- Active resolver 成为性能热点：建立按 scope/type 的 read projection，但 Authority 仍是 activation records。