# AC-17 Legacy LocalStorage 迁移与退役

状态：`PLANNED`  
阶段：Phase 5 / Migration and Proof  
前置依赖：AC-03 至 AC-16

2026-08-03 有限修订：关键 Legacy Writer 切换是每条纵向 Slice 的 Gate 项；Track F 仅清理剩余非关键 Legacy。每条 Slice 必须记录 source、target、import、validation、cutover、reader compatibility 和 retirement deadline。

## 1. ADR

### 背景

Legacy LocalStorage 中既有正式生产状态，也有导入中间结果、缓存、样例、索引、导出文件和历史兼容能力。把“删除所有本地文件”作为目标会造成无价值迁移；保留生产双写又会破坏 Authority。迁移必须按数据语义和业务关键路径分类。

### 决策

将 Legacy 分为四类：

| 类别 | 定义 | 策略 |
|---|---|---|
| A | 正式生产权威状态 | 必须迁移 PostgreSQL Authority 并删除 Writer |
| B | 正式输入准备/中间产物 | 根据可重现性迁移 manifest 或保留非权威缓存 |
| C | 可重建投影、索引、导出、UI 缓存 | 可继续本地/独立存储，但不能成为 Authority |
| D | 历史兼容、无调用代码 | 冻结、归档或删除 |

迁移采用单向导入，不采用长期双写：

```text
Discover
→ Classify
→ Define Target Authority
→ Convert
→ Validate
→ Import Operation
→ Verify
→ Freeze Legacy Writer
→ Observe
→ Delete Writer
→ Archive/Delete Reader
```

## 2. 迁移波次

### Wave 0：防扩散

- 禁止新增 LocalStorage 正式实体；
- production composition root 禁止新 Legacy writer；
- 新 Legacy 例外必须有到期日和删除任务；
- 建立写路径扫描和 runtime evidence。

### Wave 1：Root 与执行状态

Project、Workspace、Book、Operation、Saga、Attempt、Effect、Receipt、Audit、Outbox。

### Wave 2：核心创作资产

BookDesign、World/Character、Book/Volume/Arc/Group/Chapter plans、Draft、Review、Revision、Export、Release。

### Wave 3：长篇状态与质量

Canon、ChapterOutcome、StoryState、Recap、Reader Outcome、QualityEvidence、ReviewIssue、Gate。

### Wave 4：Source/MKAOS/Context

SourceSnapshot、eligibility、Knowledge assets、KnowledgePack、ContextManifest、ActualSentContext。

### Wave 5：Publishing/Feedback/Portfolio 与剩余工具

按真实生产调用图决定 migrate/retain/delete。

## 3. 迁移原则

- 每次迁移是 Authority Operation，具备 batch identity、idempotency、digest 和 audit；
- 转换脚本必须版本化；
- 先 shadow read/compare，再切换读路径；
- 先冻结 writer，再观察，再删除；
- 迁移失败不得部分静默成功；
- 无法解释的记录 quarantine；
- 不为追求数量迁移可重建缓存；
- 回滚指恢复读路由或创建补偿导入，不把 PostgreSQL 结果回写 Legacy。

## 4. 代码位置

### 当前重点

- LocalStorage/workspace/storage modules；
- `src/novel_forge/api/legacy_app.py`
- Legacy CLI commands；
- product routers/services 直接文件写；
- Celery/local worker paths；
- `.local/workspace`、demo/sample paths；
- Docker/Makefile 中 Legacy command；
- 当前 PostgreSQL Authority repositories/migrations。

### 目标新增

- `src/novel_forge/storage/legacy_readonly/`
- `src/novel_forge/modules/legacy_migration/contracts.py`
- `.../application.py`
- `.../converters/`
- `.../verification.py`
- `.../quarantine.py`
- `scripts/migrations/legacy_inventory.py`
- `scripts/migrations/legacy_wave_runner.py`
- `tests/integration/test_legacy_migration_postgres.py`

### 禁止位置

- 新 Domain Service 写 LocalStorage；
- Authority 成功后继续同步写 Legacy；
- 迁移脚本绕过 Operation/Audit 直接修改多域表；
- 读取 Legacy 失败时返回空对象继续生产；
- 以删除文件代替验证数据已迁移。

## 5. 迁移脚本规范

每个 converter 必须实现：

```text
source_type
source_schema_version
target_asset_type
conversion_version
read_source()
validate_source()
convert()
validate_target()
compute_digests()
import_idempotently()
verify()
```

通用脚本：

```text
scripts/migrations/legacy_inventory.py
scripts/migrations/legacy_classification_report.py
scripts/migrations/legacy_dry_run.py
scripts/migrations/legacy_import_batch.py
scripts/migrations/legacy_verify_batch.py
scripts/migrations/legacy_drift_report.py
scripts/migrations/legacy_freeze_writer.py
scripts/migrations/legacy_retirement_check.py
```

每一领域的 SQL migration 从当前 migration head 分配，不在本计划预占序号。

## 6. 实施计划

1. 使用静态扫描 + runtime tracing 生成 Legacy 读写调用图。
2. 对每个路径分类 A/B/C/D，并指定 Owner 和退役 Gate。
3. 立即启用防扩散 CI。
4. 按 Wave 1–5 实施 converter、dry-run、import、verify。
5. 双读对比仅用于迁移观察，不允许双写。
6. 切换 production reader 到 Authority。
7. 冻结/删除 Legacy writer，保留只读兼容期。
8. 运行 L3/L10/L30、恢复和回滚演练。
9. 删除无调用代码和配置，更新 docs/current state。

## 7. 测试矩阵

| 测试 | 场景 | 通过条件 |
|---|---|---|
| Inventory | 所有写路径 | 均有分类/Owner |
| Dry run | 不写数据库 | 输出目标、冲突和校验报告 |
| Idempotency | 同 batch 重跑 | 不重复版本 |
| Digest | source 变化 | 检测冲突，不覆盖已有 import |
| Partial failure | batch 中一条失败 | 按事务边界回滚/隔离且可恢复 |
| Scope | 数据归属不明 | quarantine |
| Dual read | Legacy/Authority 对比 | 差异可解释并达阈值 |
| Freeze writer | production 调旧 writer | fail closed |
| Authority-only | 移除 Legacy 目录 | 核心生产链正常 |
| Rollback rehearsal | 切换失败 | 恢复 reader route，不丢 Authority 数据 |
| Long chain | 迁移后 L10/L30 | 无 Legacy 正式写入 |

## 8. Acceptance Gate

```text
legacy_inventory_complete=true
legacy_paths_classified=true
new_legacy_authority_writes_blocked=true
critical_path_legacy_data_migrated=true
production_legacy_writers_zero=true
production_authority_reads_only=true
migration_idempotency_and_verification_proven=true
legacy_readonly_retirement_schedule_active=true
```

Architecture Closure 不要求所有 C 类缓存删除，但 A 类生产权威状态和关键路径 Writer 必须清零。

## 9. 风险

- 迁移范围无限扩大：按全书关键路径和调用图排序。
- 历史数据质量差：quarantine 并保留原始 digest，不猜测修复。
- 长期只读兼容无法删除：每项设置调用量阈值、到期日和 Owner。
- 切换后性能下降：在 Authority 上建立 projection/index，不回退 Legacy。
