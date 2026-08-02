# AC-18 Architecture Fitness Tests

状态：`PLANNED`  
阶段：Phase 0–5 / Continuous Enforcement  
前置依赖：AC-00 基线；其余工作包持续接入

## 1. ADR

### 背景

架构原则如果只存在于文档和 Code Review 中，会随着模块扩展重新出现跨层 import、直接 Provider 调用、LocalStorage 正式写入、第二套状态机、未版本化公共契约和缺失 Scope。Novel OS 代码规模与模块数量已不适合依赖人工记忆维持边界。

### 决策

建立 Architecture Fitness Test Suite，并作为 CI 必过 Gate。每项核心 ADR 必须至少映射一个自动化检查；无法自动检查的决策必须具备 manifest、CODEOWNER 和 PR checklist。

检查分为：

- Static architecture；
- Contract/schema；
- PostgreSQL constraints；
- Runtime composition；
- Failure injection；
- Migration compatibility；
- Long-chain acceptance。

## 2. 强制测试集合

### 2.1 Repository Integrity

验证 module、migration、worker、test、console script、deployment manifest 与文件树一致；显式测试 pattern 收集数不得为 0。

### 2.2 Import Boundary

检查 Domain 不依赖 API、Infrastructure、Provider SDK、LocalStorage；Context 之间依赖符合 context map；无循环依赖。

### 2.3 Direct External Call Scan

扫描 OpenAI/Anthropic SDK、`httpx/requests` 外部调用、socket/subprocess 模型执行。只允许在 `production_execution/backends` 或批准 adapter 白名单中出现。

### 2.4 Direct Legacy Write Scan

扫描 `Path.write_*`、`json.dump`、LocalStorage save/write。生产领域只允许 Object Store adapter、export/caching 白名单，且必须标记 non-authoritative。

### 2.5 Operation Coverage

每个正式 CLI/API/Worker/Agent/平台入口必须映射 OperationDefinition。禁止新增未登记 production entrypoint。

### 2.6 Asset Immutability

核心资产写入必须创建 AssetVersion；数据库触发器/权限和 Repository 测试阻止原地修改。

### 2.7 Scope Propagation

Operation、Saga、Attempt、Effect、Receipt、AssetVersion、Event 必须保持 project/workspace/book 一致。跨书引用负向测试必须失败。

### 2.8 Migration Chain

验证唯一 head、无断链、registry 完整、upgrade from empty、upgrade from supported baseline、schema checksum、rollback/forward-fix policy。

### 2.9 Worker Manifest

每个 Worker 有 entrypoint、deployment unit、capability、queue、health、lease/recovery 和最小 boot test。

### 2.10 Authority-only Boot

在无 Legacy workspace、无 local fallback 条件下启动 API、关键 Worker、PostgreSQL 和 Object Store，并完成最小 Operation。

### 2.11 Replay and Failure Injection

覆盖 StoryState replay、Worker crash、lease expiry、stale fence、Provider timeout/UNKNOWN、duplicate callback、cancel race、late result、DB restart、outbox replay。

### 2.12 Evidence Classification

测试 Fixture、scripted backend、sandbox、real provider、longform、production flags 不得互相升级。报告生成器必须根据证据自动分类。

## 3. 代码位置

### 目标目录

```text
tests/architecture/
tests/contract/
tests/failure_injection/
tests/deployment/
scripts/architecture/
architecture/manifests/
```

建议测试：

- `test_repository_manifest.py`
- `test_import_boundaries.py`
- `test_external_call_boundaries.py`
- `test_legacy_write_boundaries.py`
- `test_operation_coverage.py`
- `test_asset_immutability.py`
- `test_scope_propagation.py`
- `test_migration_integrity.py`
- `test_worker_manifest.py`
- `test_evidence_classification.py`

CI 建议新增：

```text
architecture-static
contract-compatibility
postgres-authority
failure-injection
migration-rehearsal
authority-only-smoke
long-chain-gates
```

## 4. 迁移脚本设计

本工作包通常不创建业务 migration，但负责验证所有 migration。新增：

```text
scripts/architecture/snapshot_schema.py
scripts/architecture/compare_schema_snapshot.py
scripts/architecture/check_migration_chain.py
scripts/architecture/check_supported_upgrade_paths.py
scripts/architecture/check_database_constraints.py
```

Schema snapshot 只用于检测差异，不取代 migration 作为 Authority。

## 5. 实施计划

1. 先实现 AC-00 integrity、import boundary、direct call/write scans。
2. 建立 ADR→Fitness Test 映射表。
3. 将 Operation coverage、Asset immutability、Scope propagation 接入 Phase 1。
4. 将 Plan/State/Context/Agent/Provider/Quality contract tests 接入 Phase 2–3。
5. 将 Authority-only boot、security、backup/recovery 接入 Phase 4。
6. 建立 failure injection 和 L3/L10/L30 gates。
7. 将所有关键 jobs 设置为 branch protection required checks。
8. 定期执行 mutation test：有意注入违规，证明 CI 真能失败。

## 6. 测试矩阵

| 层级 | 执行频率 | 内容 |
|---|---|---|
| PR fast | 每 PR | manifest、imports、direct calls/writes、contracts、compile |
| PR database | Authority 变更 | migration、constraints、PG integration |
| Nightly | 每日 | failure injection、authority-only stack、replay |
| Weekly | 每周 | backup/restore、PITR、L10、cost/context growth |
| Milestone | 阶段 Gate | L30、真实 Provider、平台 sandbox、多 Worker recovery |

负向样例必须包括：

- Domain import OpenAI SDK；
- production module 写 LocalStorage；
- 新 API 未绑定 Operation；
- 修改已批准 AssetVersion；
- Book A 引用 Book B 私有状态；
- timeout 直接变 FAILED；
- Fixture 报告声称 real provider；
- migration registry 引用缺失文件。

## 7. Acceptance Gate

```text
architecture_fitness_suite_active=true
core_adrs_have_enforcement=true
required_ci_checks_configured=true
negative_mutation_cases_fail=true
authority_only_smoke_green=true
failure_injection_suite_green=true
migration_rehearsal_green=true
evidence_classification_automated=true
```

Architecture Closure 总 Gate 不得在 Fitness Tests 被 skip、xfail 或只运行空测试集合时通过。

## 8. 风险

- 静态扫描误报：采用 AST/import graph 和明确 adapter 白名单，不依赖简单字符串匹配作为唯一证据。
- CI 过慢：按 fast/database/nightly/milestone 分层，但关键边界必须在 PR fast 中覆盖。
- 白名单不断扩大：每个例外绑定 ADR exception 和到期日。
- 测试只证明 Fixture：证据分类检查必须阻止将本地结果升级为真实/生产证明。