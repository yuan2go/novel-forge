# AC-04 Project、Workspace、Book 与 Scope

状态：`PLANNED`  
阶段：Phase 1 / Shared Kernel Closure  
前置依赖：AC-02、AC-03

## 1. ADR

### 背景

当前系统同时存在本地 workspace、project_id、book 资产、Authority operation、Agent scope 和 API operator identity。若这些身份没有统一约束，跨书污染、错误资产读取、越权提交、恢复时找不到正确上下文等问题会在多书和全书自治阶段集中暴露。

### 决策

所有正式生产对象必须绑定统一的层级身份和不可变作用域快照：

```text
Tenant（预留）
└── Project
    └── Workspace
        └── Book
            ├── Volume
            ├── Arc
            ├── ChapterGroup
            └── Chapter
```

当前可将 Tenant 固定为单租户默认值，但数据库和契约不得把“全局唯一且无隔离”写死。

### Scope 类型

- Narrative Scope：允许操作的 Book/Volume/Arc/Chapter 范围；
- Asset Read Scope：允许读取的 AssetVersion；
- Candidate Write Scope：允许产生的候选资产类型；
- Authority Scope：允许提交到哪些 Authority；
- Temporal Scope：允许影响历史、当前或未来区间；
- Knowledge Visibility Scope：允许读取的 Source/KnowledgePack；
- Execution Scope：允许使用的 Capability、Backend、预算和工具；
- External Action Scope：允许触发的平台、环境和副作用。

Scope 必须冻结为 Snapshot；需要扩大时创建新的 ScopeExpansionRequest 和 Snapshot，不得原地修改。

## 2. 核心模型

### Project

拥有产品级边界、默认策略、成员和环境配置引用。Project 不是文件目录。

### Workspace

表示可操作工作空间和分支/环境边界，可关联 object prefix、git ref、数据隔离和运行策略。Local path 只是 adapter 属性，不是 Workspace identity。

### Book

表示独立小说生产根。Book 拥有设计、计划、状态、成本和发布生命周期，但不直接包含所有可变 JSON。

### Production Scope Snapshot

至少包括：

```text
scope_snapshot_id
project_id
workspace_id
book_id
narrative_range
asset_read_versions
candidate_types
authority_permissions
knowledge_pack_versions
temporal_policy
execution_capabilities
external_action_policy
created_by
created_at
content_hash
```

## 3. 实施范围

1. 统一所有 Authority tables 的 project/workspace/book 外键或强校验。
2. 所有 Operation/Saga/Attempt、AssetVersion、Effect、Receipt、Event 绑定 scope identity。
3. API 从可信身份解析 scope，不接受客户端随意声明 operator 权限。
4. Worker 只能领取与自身 service account scope 匹配的任务。
5. 跨书查询必须显式使用 portfolio projection，不能默认全局扫描并混合上下文。
6. Context Builder 和 MKAOS selection 必须消费冻结 scope。

## 4. 代码位置

### 当前重点

- `src/novel_forge/modules/project_authority/`（存在性先由 AC-00 验证）
- `src/novel_forge/modules/book_authority/`
- `src/novel_forge/modules/authority_security/`
- `src/novel_forge/modules/agent_collaboration/`
- `src/novel_forge/modules/command_kernel/`
- `src/novel_forge/api/authority_dependencies.py`
- `src/novel_forge/api/authority_app.py`
- Project/Workspace/Book schemas and migrations

### 目标新增或收敛

- `src/novel_forge/core/identity.py`
- `src/novel_forge/core/scope.py`
- `src/novel_forge/modules/project_authority/contracts.py`
- `src/novel_forge/modules/project_authority/application.py`
- `src/novel_forge/modules/project_authority/repositories.py`
- `tests/architecture/test_scope_propagation.py`
- `tests/integration/test_project_book_isolation_postgres.py`

### 禁止位置

- 业务 Service 使用固定 `*` scope；
- production API 默认 local operator 全权限；
- 通过 workspace path 推断 project/book；
- Worker 从 payload 读取未验证的权限；
- AssetVersion 缺少 book identity 却进入生产链。

## 5. 迁移脚本设计

数据库迁移内容：

- 建立或补齐 Project、Workspace、Book authority roots；
- 为核心表补充 project_id/workspace_id/book_id；
- 建立复合外键、scope consistency trigger 或 deferred validation；
- 建立 ScopeSnapshot 与 ScopeExpansionRequest；
- 为历史记录生成可追溯默认 scope，不允许直接填充无证据 wildcard。

脚本规范：

```text
scripts/migrations/inventory_scope_gaps.py
scripts/migrations/backfill_project_workspace_book_scope.py
scripts/migrations/verify_scope_consistency.py
scripts/migrations/quarantine_unscoped_records.py
```

无法可靠归属的记录进入 quarantine，不得自动归入默认书。

## 6. 实施计划

1. 枚举所有正式表和事件中的 identity 字段。
2. 定义 Canonical ID 类型、外键和 scope hash。
3. 建立 Project/Workspace/Book roots 与创建 Operation。
4. 建立 ScopeSnapshot/Expansion 模型。
5. 将 API identity resolver、Command admission、Context、Agent 和 Worker 统一接入 scope。
6. 回填历史数据并隔离无法识别记录。
7. 增加跨书污染测试和权限负向测试。
8. 移除 production wildcard operator。

## 7. 测试矩阵

| 测试 | 场景 | 通过条件 |
|---|---|---|
| Identity unit | 非法/空 ID | 合同拒绝 |
| Scope hash | 相同输入重建 | hash 稳定 |
| Cross-book FK | Book A operation 引用 Book B asset | DB/应用拒绝 |
| API auth | 客户端伪造 project_id | 使用可信身份解析并拒绝越权 |
| Worker claim | service account scope 不匹配 | 不领取任务 |
| Context isolation | 两本书同名角色 | 不混入另一 Book 资产 |
| MKAOS visibility | pack 不在 scope | selection 拒绝 |
| Expansion | Agent 申请额外范围 | 生成新 Snapshot，不修改旧 Snapshot |
| Legacy backfill | 无法确认归属 | quarantine |
| Portfolio read | 跨书 dashboard | 只读 projection，不开放跨书写 |

## 8. Acceptance Gate

```text
project_workspace_book_roots_authoritative=true
production_objects_scope_bound=true
scope_snapshots_immutable=true
scope_expansion_governed=true
cross_book_write_isolation_verified=true
cross_book_context_isolation_verified=true
trusted_identity_scope_resolution=true
production_wildcard_operator_disabled=true
```

## 9. 风险与控制

- 为未来 SaaS 过度设计：只预留 tenant_id 和隔离契约，不实现复杂计费。
- 大规模补字段锁表：使用分阶段 nullable→backfill→validate→not null。
- 历史数据归属不明：quarantine 而非猜测。
- Scope 过大影响性能：Snapshot 存引用与 digest，大清单可放 object store，由 PostgreSQL manifest 约束。