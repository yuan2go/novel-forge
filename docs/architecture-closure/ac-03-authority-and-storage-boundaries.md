# AC-03 Authority 与存储边界

状态：`PLANNED`  
阶段：Phase 1 / Shared Kernel Closure  
前置依赖：AC-01、AC-02

## 1. ADR

### 背景

当前系统同时存在 PostgreSQL Authority、Legacy LocalStorage、Object Store、向量存储、Redis/Queue 和浏览器缓存。若未明确哪些存储是正式 Authority、哪些只是派生或缓存，后续全书自治会产生双写、读到旧状态、恢复歧义和跨存储事务问题。

### 决策

生产环境采用以下权威模型：

| 数据类别 | 主存储 | Authority | 可重建 |
|---|---|---:|---:|
| Operation/Saga/Attempt/Lease/Receipt | PostgreSQL | 是 | 否 |
| Asset/AssetVersion/Decision/Dependency | PostgreSQL | 是 | 否 |
| Canon/StoryState/Plan/Quality Gate | PostgreSQL | 是 | 可回放但不可丢失 |
| 大型输入输出、附件、导出文件 | Object Store | PostgreSQL 引用为权威 | 部分 |
| Vector/Embedding/Search Index | pgvector/Qdrant/其他索引 | 否 | 是 |
| Queue/Redis 状态 | Queue/Redis | 否 | 是 |
| Local 临时文件与开发样例 | LocalStorage | 否 | 是 |
| UI/browser 缓存 | Browser | 否 | 是 |

生产正式状态只能由 PostgreSQL Authority 决定。Object Store 的 blob 只有被已提交 PostgreSQL manifest 引用后才具有正式意义。Vector Store、Redis、Queue 和 LocalStorage 不得反向覆盖 Authority。

### 双写决策

禁止长期双写。迁移采用：

```text
Legacy Read
→ Convert
→ Validate
→ Authority Import Operation
→ Verify
→ Freeze Legacy Writer
→ Observe
→ Retire
```

不允许把 `PostgreSQL write + LocalStorage write` 作为稳定架构。

## 2. 实施范围

### 2.1 数据所有权目录

新增 `architecture/data-ownership.yaml`，每项记录：

```text
entity
owner_context
authority_store
writer
readers
versioning
retention
recovery
object_store_policy
projection_policy
legacy_source
legacy_status
```

### 2.2 Authority Store Contract

正式 Repository 必须具备：

- transaction/UoW；
- immutable version insert；
- optimistic/constraint conflict；
- idempotency；
- audit/outbox；
- project/book scope；
- soft delete/retention policy；
- read projection 与 write model 分离。

### 2.3 Object Store Contract

Object Store 写入流程：

```text
stage blob
→ calculate digest
→ persist object metadata
→ validate size/type
→ commit manifest reference in PostgreSQL
→ mark blob committed
```

孤儿 blob 必须可回收；数据库记录不能引用未验证对象。

### 2.4 Projection Contract

向量索引、搜索索引和只读 dashboard projection 必须保存 source version/checkpoint。重建不会改变正式状态。

## 3. 代码位置

### 当前证据

- `src/novel_forge/storage/`
- `src/novel_forge/storage/authority_uow.py`
- `src/novel_forge/storage/authority_repositories.py`
- `src/novel_forge/storage/migrations/`
- `src/novel_forge/modules/command_kernel/`
- `src/novel_forge/modules/pgvector_store/`
- LocalStorage 与 workspace 相关模块
- Object Store/MinIO composition in `docker-compose.yml`

### 目标新增或收敛

- `src/novel_forge/core/storage_contracts.py`
- `src/novel_forge/storage/postgres/`
- `src/novel_forge/storage/object_store/`
- `src/novel_forge/storage/projections/`
- `src/novel_forge/storage/legacy_readonly/`
- `architecture/data-ownership.yaml`
- `tests/architecture/test_data_ownership.py`

不要求一次性移动全部实现，但必须让 production composition root 只装配 PostgreSQL Authority writer。

### 禁止位置

- Domain Service 中直接 `Path.write_text` 或 `json.dump` 正式资产；
- Router 中直接跨存储写；
- Worker 用 Redis 状态决定正式完成；
- Vector Store 结果直接激活 Plan/Canon；
- Object Store key 被当作业务状态。

## 4. 迁移脚本设计

需要建立通用迁移框架：

```text
scripts/migrations/inventory_legacy_storage.py
scripts/migrations/export_legacy_records.py
scripts/migrations/convert_legacy_record.py
scripts/migrations/import_authority_records.py
scripts/migrations/verify_authority_import.py
scripts/migrations/freeze_legacy_writers.py
scripts/migrations/report_storage_drift.py
```

数据库 migration 由具体领域 AC 分配，不在本工作包预占编号。通用 migration metadata 表可考虑：

```text
legacy_import_batches
legacy_import_items
legacy_import_failures
legacy_import_verifications
```

每个 item 保存 source digest、target identity、target version、conversion version、结果和可重放证据。

## 5. 实施计划

1. 扫描所有文件、表、对象存储、向量和缓存写路径。
2. 为每类实体确定 Owner、Authority store 和唯一 writer。
3. 将生产 composition root 的 Legacy writer 替换为 fail-closed adapter。
4. 建立 Object Store staged/committed lifecycle。
5. 为 projection 增加 checkpoint 和 rebuild command。
6. 建立 legacy import batch framework。
7. 在 CI 扫描新增 LocalStorage 正式写入。
8. 通过 Authority-only 无本地工作区启动验证。

## 6. 测试矩阵

| 测试 | 场景 | 通过条件 |
|---|---|---|
| Ownership schema | 实体无 Owner/多个 Writer | CI 失败 |
| Production boot | 无 `.local/workspace` | Authority 栈可启动 |
| Legacy write negative | production 调用 LocalStorage writer | fail closed |
| Object staging | blob 成功、DB commit 失败 | blob 保持 orphan/staged，可回收 |
| Missing blob | DB manifest 引用不存在对象 | commit 被拒绝或健康失败 |
| Projection rebuild | 删除向量索引后重建 | 正式数据不变化，结果 checkpoint 一致 |
| Import idempotency | 同批次重复导入 | 不重复创建版本 |
| Drift check | Legacy 与 Authority 不同 | 报告差异，不自动覆盖 Authority |
| Transaction | audit/outbox 与状态提交 | 同事务成功或回滚 |

## 7. Acceptance Gate

```text
data_ownership_catalog_complete=true
production_authority_store_postgresql=true
production_legacy_writers_disabled=true
silent_storage_fallback_disabled=true
object_store_commit_protocol_verified=true
projection_rebuild_verified=true
legacy_import_framework_verified=true
cross_store_authority_ambiguity_zero=true
```

## 8. 风险与控制

- PostgreSQL 存储大型正文导致膨胀：正文可放 Object Store，但 PostgreSQL 保留不可变 manifest、digest、版本和权限。
- 禁用 Legacy 影响开发体验：保留 development-only adapter，必须显式配置且写入 evidence 标记 non-authoritative。
- 跨存储事务无法原子：使用 staged blob、数据库 manifest 和 orphan collector，而非伪分布式事务。
- 向量重建成本高：保存可重复 embedding profile、source version 和 batch checkpoint。