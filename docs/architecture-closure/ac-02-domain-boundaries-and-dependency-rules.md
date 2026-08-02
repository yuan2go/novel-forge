# AC-02 领域边界与依赖规则

状态：`PLANNED`  
阶段：Phase 1 / Shared Kernel Closure  
前置依赖：AC-00、AC-01

## 1. ADR

### 背景

Novel Forge 已包含大量模块，既有 LocalStorage 产品能力，也有 PostgreSQL Authority、Execution Plane、Chapter/Book Authority 和新 Authority imports。若不先固定 Bounded Context、数据所有权和依赖方向，后续迁移会把旧模块直接包进新模块，形成跨域表访问、双向依赖和多个正式 Writer。

### 决策

将系统划分为稳定的领域边界，并强制单向依赖：

```text
API/UI/Workers
→ Application Use Cases
→ Domain Authorities and Domain Services
→ Shared Contracts and Ports
← Infrastructure Adapters
```

领域层不得依赖 FastAPI、Next.js、PostgreSQL driver、Provider SDK、LocalStorage 或具体 Queue 实现。

### 核心 Bounded Context

- Project Authority；
- Source Authority；
- MKAOS Authority；
- Book Design Authority；
- Planning Authority；
- Chapter Authority；
- Longform Authority；
- Quality/Eval Authority；
- Publishing Authority；
- Production Execution Authority；
- Agent Collaboration；
- Portfolio/Resource Governance。

每种正式实体只能有一个 Owner Context。其他 Context 通过版本化 Snapshot、Query Port、Command 或 Domain Event 使用，不得直接更新 Owner 的表。

## 2. 领域所有权

| Context | 拥有的正式状态 | 不负责 |
|---|---|---|
| Project | Project、Workspace、Book identity、environment、policy refs | 小说内容生成 |
| Source | SourceDocument、Snapshot、license、eligibility、risk、quarantine | 知识卡与创作决策 |
| MKAOS | KnowledgeCard、Rule、Template、Pack、usage、feedback、weight | Canon 与计划激活 |
| Book Design | Theme、Ending、World/Character design、reader promise | 章节正文和生产调度 |
| Planning | Book/Volume/Arc/ChapterGroup/Chapter plans、replan、impact | 正文生成与 Canon commit |
| Chapter | 单章 Saga、Draft、Review、Revision、chapter quality、release | 全书计划所有权 |
| Longform | Canon、ChapterOutcome、StoryState、recap、deviation | Provider 路由 |
| Quality | Judge profile、evaluation evidence、calibration、gate | 修改被评资产 |
| Publishing | Release package、submission、receipt、withdrawal、feedback import | 直接生成正文 |
| Execution | Backend、route、effect、receipt、cost、reconciliation | 领域接受和资产激活 |
| Agent | WorkOrder、Turn、Candidate、Conflict | 正式领域状态 commit |

## 3. 实施范围

### 3.1 Context Map

建立机器可读 `architecture/domain-context-map.yaml`，字段包括：

```text
context
owned_entities
owned_tables
public_commands
public_queries
published_events
consumed_events
allowed_dependencies
forbidden_dependencies
legacy_adapters
owner_team
```

### 3.2 端口与适配器

每个 Context 应区分：

- `contracts.py`：稳定输入输出契约；
- `domain.py`：纯领域规则；
- `application.py`：用例编排和 UoW；
- `ports.py`：Repository、Execution、Clock 等接口；
- `adapters/`：PostgreSQL、Object Store、Provider 等实现；
- `api/` 或 router：外部入口。

不要求一次重排全部目录，但新代码必须遵守，旧代码按 AC-17 分批迁移。

### 3.3 跨域访问规则

允许：

```text
Planning reads frozen BookDesign Snapshot
Chapter reads active ChapterPlan Version
Longform consumes accepted ChapterOutcome
Quality evaluates immutable target AssetVersion
```

禁止：

```text
Chapter updates planning tables
Agent writes canon tables
Quality rewrites draft content
API router commits multiple domains without application UoW
MKAOS activates BookPlan
```

## 4. 代码位置

### 当前证据路径

- `src/novel_forge/modules/command_kernel/`
- `src/novel_forge/modules/production_execution/`
- `src/novel_forge/modules/chapter_authority/`
- `src/novel_forge/modules/book_authority/`
- `src/novel_forge/modules/book_followup_authority/`
- `src/novel_forge/modules/context_builder/`
- `src/novel_forge/modules/canon_graph/`
- `src/novel_forge/modules/quality_eval/`
- `src/novel_forge/modules/evaluation_center/`
- `src/novel_forge/modules/agent_collaboration/`
- `src/novel_forge/modules/source_intake/`
- `src/novel_forge/modules/mkaos*/`

Project/Source/MKAOS Authority 新路径必须由 AC-00 确认当前 HEAD 是否实际存在。

### 目标新增

- `architecture/domain-context-map.yaml`
- `src/novel_forge/core/domain_contracts/`
- `scripts/architecture/check_domain_dependencies.py`
- `tests/architecture/test_domain_boundaries.py`

### 禁止依赖

领域包内禁止 import：

- `fastapi`；
- `psycopg`；
- `httpx`、`requests`；
- OpenAI/Anthropic SDK；
- `novel_forge.api`；
- `legacy_app`、`LocalStorage`；
- 前端或 CLI 模块。

例外只能位于明确的 adapter/composition root。

## 5. 迁移脚本设计

本工作包主要是代码边界迁移。数据 migration 仅在拆分表所有权或增加跨域引用时实施。

建议脚本：

- `scripts/architecture/build_import_graph.py`
- `scripts/architecture/report_cross_context_table_access.py`
- `scripts/architecture/generate_context_ownership_report.py`
- `scripts/migrations/audit_domain_data_ownership.py`

如果发现一张表被多个领域写入，先生成 ownership report，再在对应 AC 工作包中设计数据迁移；不得在 AC-02 中盲目拆表。

## 6. 实施计划

1. 从实际 import、Repository 和 SQL 调用生成当前依赖图。
2. 将实体、表、Command、Query、Event 分配给唯一 Context。
3. 标记跨域直接写、循环 import 和共享 mutable dict。
4. 定义每个 Context 的 public contract 和内部实现边界。
5. 引入 query ports/snapshots 替换直接表读取。
6. 引入 application service 替换 router/worker 中的跨域事务。
7. 为遗留违规建立 AC-17 迁移条目和到期时间。
8. 在 CI 启用依赖规则。

## 7. 测试矩阵

| 测试 | 场景 | 通过条件 |
|---|---|---|
| Import graph | Domain import API/SDK/LocalStorage | CI 失败 |
| Ownership | 同一实体有两个 Owner | CI 失败 |
| SQL access | 非 Owner 更新表 | CI 失败或明确 adapter 例外 |
| Contract version | 跨域任意 dict | 必须改为版本化 contract |
| UoW boundary | Router 直接协调多 Repository | 测试阻止 |
| Circular dependency | Context A↔B | 无循环 |
| Event compatibility | consumer 读取旧 event version | 兼容或显式迁移 |
| Negative | Quality 直接修改 Draft | 领域测试失败 |

## 8. Acceptance Gate

```text
domain_context_map_complete=true
entity_ownership_unique=true
table_writer_ownership_unique=true
cross_context_contracts_versioned=true
domain_dependency_ci_active=true
forbidden_domain_imports_zero=true
unbounded_cross_context_writes_zero=true
```

允许存在登记的 Legacy adapter，但必须具备 Owner、范围、到期日和 AC-17 删除计划。

## 9. 风险与控制

- 过度微服务化：本工作包定义逻辑边界，不要求部署拆分。
- 大规模目录搬迁造成回归：优先建立 facade、port 和测试，再渐进移动。
- Shared Kernel 膨胀：只允许身份、版本、错误、时间、事件 Envelope 等真正跨域契约。
- 跨域查询性能下降：允许只读 projection，但 projection 不能成为反向 Authority。