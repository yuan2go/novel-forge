# Novel Forge V7 代码审计与文档重基线

更新时间：2026-08-01  
审计分支：`feat/v7-content-intelligence-and-longform-proof`  
审计 HEAD：`aa991b53039cdf2e4e7911d4483052b9a6a752a1`

## 1. 文档定位

本文是 2026-08-01 之后判断当前工程状态的首要审计报告。代码、数据库迁移和当前测试实现优先于历史报告；蓝图和设计文档描述目标，不构成实现证明。

结论必须区分三类证据：

- **代码事实**：当前分支可读取源码、配置、迁移或测试中存在的实现；
- **运行验证**：针对当前完整 HEAD 实际执行并通过的命令；
- **合理推断**：根据代码结构得出的判断，必须继续用本地 checkout 或 CI 复核。

本次远程审计未获得可用本地 checkout，未实际运行 Python、PostgreSQL、前端或 Docker 测试。历史测试报告不能替代当前 HEAD 的运行验证。

## 2. 总体判断

Novel Forge 已经形成较完整的内容生产控制底座：

```text
PostgreSQL Authority
+ Operation / Saga / Attempt
+ Lease / Fencing Token
+ AssetVersion
+ External Effect / Receipt
+ Chapter Authority
+ Book Authority
+ Canon / Story State
+ Quality Evidence
+ Provider Control
```

当前最成熟的是 Command Kernel、PostgreSQL Authority 不变量和单章生产协议。当前尚未被真实证明的是：

```text
真实 Provider
真实模型质量与成本
全书自治生产
百万字长篇稳定性
多书并行
真实平台发布
真实反馈校准
生产部署与灾难恢复
```

当前阶段应定义为：

```text
ARCHITECTURALLY_ADVANCED
BUT_HEAD_INTEGRITY_AND_PRODUCTION_RUNTIME_BLOCKED
```

## 3. 当前 HEAD 完整性风险

当前引用方已出现以下新增模块：

```text
novel_forge.modules.project_authority
novel_forge.modules.task_authority
novel_forge.modules.source_authority
novel_forge.modules.mkaos_authority
novel_forge.workers.source_authority
novel_forge.workers.mkaos_authority
```

迁移索引已加入 `0043` 至 `0050`，测试收集脚本也加入 Source/MKAOS Authority 测试名称。但通过同一分支和精确 HEAD 读取部分目标文件时返回不存在。

该现象可能来自：

1. 引用代码已提交，但新增文件仍是未跟踪文件或未进入提交；
2. 最新提交遗漏部分模块、迁移或测试；
3. GitHub 私有仓库内容接口发生索引异常。

在本地 checkout 完成下列检查前，不得声明当前 HEAD 可构建：

```bash
git status --short
git ls-files src/novel_forge/modules/project_authority
git ls-files src/novel_forge/modules/task_authority
git ls-files src/novel_forge/modules/source_authority
git ls-files src/novel_forge/modules/mkaos_authority
git ls-files src/novel_forge/storage/migrations/versions/v20260801_00*
git ls-files tests/integration/test_*authority_postgres.py
python -c "import novel_forge.api.authority_app"
python -c "import novel_forge.storage.migrations"
```

CI 必须增加“所有导入目标、迁移索引目标、console script 目标和必需测试模块均存在”的静态检查。

## 4. 实际架构

### 4.1 双运行面

系统目前存在两套运行面：

```text
Legacy Local-first Runtime
PostgreSQL Authority Runtime
```

生产 API 选择器在 `storage_authority=postgresql` 时进入 Authority API；生产环境禁止 Legacy Authority。但开发环境默认仍为：

```text
environment=development
storage_authority=legacy_local
```

Legacy API 仍保留 LocalStorage、pipeline wrapper、Celery 和 PostgreSQL 读取回退。Authority API 则通过 Project、Task、Asset、Source、MKAOS、Chapter、Content、Book、Canon 和 Provider Callback 路由构建 PostgreSQL-only surface。

在 Authority 迁移完成前，任何新生产功能不得新增第三套入口，也不得绕过 Operation、AssetVersion、External Effect 和审计证据。

### 4.2 Command Kernel

Command Kernel 已具备：

- Operation Definition 版本冻结；
- Command Schema、权限和审批校验；
- 幂等键与 Request Digest 冲突检测；
- Operation 状态 CAS；
- Saga 与 Operation Dependency；
- Attempt、Retry、Lease 和 Fencing Token；
- Cancellation、Compensation 和迟到结果证据；
- External Effect、Dispatch、Receipt、Inbox、Outbox；
- State Event、Audit Log 和输出 AssetVersion 绑定。

关键不变量由 PostgreSQL 的 `UNIQUE`、`CHECK`、`FOREIGN KEY`、部分唯一索引、Trigger、PL/pgSQL 函数和 `SELECT ... FOR UPDATE` 共同保证，不只是应用层约定。

### 4.3 单章生产协议

Chapter Authority 当前定义 18 个节点：

```text
Plan
→ Context
→ Draft
→ Review
→ Revision
→ Re-review
→ Canon Extraction
→ Canon Proposal
→ Canon Update
→ 5 个 Quality Group
→ Quality Aggregate
→ Publish Gate
→ Export
→ Final Release Gate
```

生产输入会冻结 ChapterPlan、上下文候选、质量策略和平台策略。Context Handler 会验证：

```text
ProductionInputManifest
== Operation 冻结输入
== Context Bundle 实际段落
```

单章集成测试对重试、Saga 恢复、陈旧 Fence、外部效果 UNKNOWN 对账、重复 Receipt、41 个质量维度证据和 9 类 Story State Snapshot 设有断言。

限制：这些证明使用确定性 Fixture，不证明真实中文正文质量、真实 Provider 行为、真实成本或长篇稳定性。

### 4.4 Book Authority

Book Authority 已实现：

- Book Root Operation 和 Saga；
- BookDesign、BookPlan、Production Profile 和 Long-form State 冻结；
- 顺序章节游标；
- 稳定章节提交键；
- Chapter Authority 子 Saga 委派；
- Chapter Acceptance；
- ChapterOutcome、StoryState 和 Canon Snapshot 推进；
- Pause、Resume、Cancel 和 Reconcile；
- Reader Outcome 与 Longform Recap 后续任务。

但当前调用方仍需逐章提供冻结 ChapterPlan、上下文候选和准备报告。Book Authority 是可靠协调器，不是已经完成的全书自治生成器。

### 4.5 Provider 与执行面

Provider v2 已有显式 Registry、Capability Profile、Route Qualification、稳定幂等键、Timeout、Query、Cancel、Callback、Usage 和 Cost Receipt 合同。

当前缺口：

- Authority composition root 未证明已经实际构造并注册真实 OpenAI Provider；
- 自动 CI 明确为 Mock-only Provider proof；
- OpenAI SDK transport 当前成本回执使用 `0 USD / not_provided`，不能作为真实财务成本；
- Provider 结果仍标记 `production_verified=false`；
- 尚无绑定当前 HEAD 的真实单章 Provider 证明。

## 5. 部署与安全风险

### 5.1 默认 Compose 未启动 Authority Runtime

当前 Docker Compose 没有默认设置完整 Authority 必需变量，例如：

```text
NOVEL_FORGE_ENVIRONMENT=production
NOVEL_FORGE_STORAGE_AUTHORITY=postgresql
NOVEL_FORGE_APPLICATION_BUILD_ID
NOVEL_FORGE_COMMIT_SHA
NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT
各阶段 Provider / Model
Provider Cost Cap
```

因此默认 CLI 会进入 Legacy Surface。Compose 的 worker 仍是 Legacy/Celery worker，独立 Chapter Authority Worker 没有进入默认部署拓扑。

### 5.2 HTTP 身份边界

Authority 路由不信任请求中的 `actor_id`，但 HTTP 层未看到 JWT、OIDC、API Key、mTLS 或用户会话认证。请求会映射为服务器配置的单一 Local Operator；默认项目范围是 `*`，权限覆盖 execute、query、cancel、recover、approve 等操作。

该模式仅适合可信单机环境，不能直接作为多用户或公网生产安全模型。

### 5.3 健康检查

Authority `/health` 仅返回静态 ready 信息，未检查：

- PostgreSQL 连通性；
- 当前 Migration；
- Authority Worker；
- Outbox Lag；
- Provider Registry；
- Object Store；
- Saga 卡死状态。

容器健康不等于业务可执行。

### 5.4 数据库运维

Authority Migration 链较完整，但大量关键迁移没有 downgrade statement。生产升级必须采用前向修复、备份恢复、蓝绿数据库或影子迁移，不能假设支持普通版本回滚。

`AuthorityUnitOfWork` 每次直接创建 psycopg 连接，尚未看到生产连接池。多书并发前应增加连接池或 PgBouncer，并验证 Scheduler 和 Worker 对数据库的压力。

## 6. 当前能力成熟度

| 能力 | 当前证据 | 结论 |
|---|---|---|
| Command Kernel | SQL 约束、迁移、仓储和集成测试 | 较成熟 |
| PostgreSQL Authority | Operation/Saga/Attempt/Asset/Effect | 较成熟，但 Authority 迁移仍在进行 |
| 单章生产 | 18 节点 Fixture 集成闭环 | 协议成熟，真实模型未证明 |
| Canon/Story State | Proposal、Approval、Patch、9 类 Snapshot | 已形成基础闭环，语义准确性未长期证明 |
| Quality | 5 组 Fan-out/Fan-in、41 维证据 | 结构完整，Judge 未生产校准 |
| Book Authority | 持久化协调、子 Saga、Acceptance | 协调较强，全书自治不足 |
| Reader Outcome | Shadow Report 和状态候选 | 未校准、非发布阻断 |
| Longform Recap | 确定性 Recap、Deviation、Replan Proposal | 有治理合同，未完成真实长篇证明 |
| Provider v2 | 控制协议和 OpenAI seam | 真实装配、成本、取消和质量未证明 |
| Source/MKAOS Authority | 当前 HEAD 引用已进入 | 完整性需优先复核 |
| Web Admin | Next.js 控制台和 Authority API 调用 | 有操作面，缺多用户鉴权和深度 E2E |
| 部署运维 | Docker 基础设施和 CI 配置 | 默认仍走 Legacy，生产闭环不足 |
| 多书生产 | Portfolio/隔离设计和部分代码 | 未完成真实并行证明 |

## 7. 当前状态标志

在完成新的运行验证前，统一使用：

```text
architecture_defined=true
command_kernel_proven=true
postgres_authority_fixture_proven=true
single_chapter_fixture_proven=true
book_coordination_fixture_proven=true

head_integrity_verified=false
current_head_build_verified=false
real_provider_proven=false
real_cost_proven=false
longform_proven=false
multi_book_proven=false
platform_publish_proven=false
production_verified=false
```

## 8. 实施优先级

### P0：恢复可构建和可部署基线

1. 修复或确认当前 HEAD 的缺失模块、迁移和测试文件；
2. 增加 import、migration target、console script 和 required test existence 检查；
3. 建立真正的 Authority Compose：API、Chapter Worker、Book Followup Worker、Callback Worker、Outbox Worker；
4. 当前 SHA 执行 compile、unit、acceptance、PostgreSQL integration、migration、web test/build 和 Docker smoke；
5. 将运行结果写入 HEAD-bound evidence report。

### P1：真实 Provider 单章闭环

1. 构造真实 Provider Registry 和凭据引用；
2. 先验证一个 Draft Stage，再扩展 Review、Revision、Canon、Quality；
3. 证明 Timeout、Query、Cancel、Callback、UNKNOWN Reconciliation；
4. 产生真实 Usage 与可核算 Cost Receipt；
5. 用中文网文样本进行人工质量验收。

### P2：全书自治执行平面

实现统一 Book Production Supervisor：

```text
BookDesign
→ Volume/Arc/ChapterGroup
→ ChapterPlan
→ Chapter Authority
→ Acceptance
→ Reader Outcome
→ Recap
→ Replan
→ Next Chapter
→ Ending
```

它必须消费冻结版本、遵循 Gate、支持暂停恢复，并且不得在域服务中隐式修改 Canon 或计划。

### P3：校准、长篇与多书证明

1. 建立 Golden Set 和编辑标注；
2. 校准 Quality Judge 与 Reader Outcome；
3. 完成 10/30/100/300 章真实 Provider 阶段证明；
4. 完成百万字稳定性与结束可达性证明；
5. 完成 3 本、10 本并行的隔离、成本、吞吐和恢复测试；
6. 最后再进入真实平台发布和反馈闭环。

## 9. 当前禁止事项

在 P0 完成前：

- 不新增平行生产 Runtime；
- 不继续扩大 Legacy 生产写入；
- 不把 Fixture Provider 称为真实 Provider；
- 不把 UI 页面存在称为业务闭环；
- 不把历史测试结果称为当前 HEAD 通过；
- 不把设计文档中的模块称为已实现；
- 不以增加更多孤立模块替代生产链闭环。
