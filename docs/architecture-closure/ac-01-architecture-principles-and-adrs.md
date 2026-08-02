# AC-01 架构原则与 ADR 治理

状态：`PLANNED`  
阶段：Phase 0 / Architecture Governance  
前置依赖：AC-00

## 1. ADR

### 背景

当前工程已经形成 PostgreSQL Authority、Command Kernel、Production Execution、Chapter Authority、Book Authority、MKAOS、Context、Quality、Agent 等大量能力，但核心原则分散在代码、设计文档和阶段报告中。缺少正式 ADR 会导致后续开发重新引入双写、第二套状态机、直接 Provider 调用、可变资产和 Agent 越权提交。

### 决策

建立一组具备强制约束力的 Architecture Decision Records。ADR 不只是说明文档，必须映射到架构测试、代码所有者、迁移策略和例外审批。

首批必须批准的 ADR：

1. PostgreSQL 是正式生产 Authority；
2. 系统只有一套 Operation/Saga/Attempt 执行模型；
3. 核心内容统一使用不可变 AssetVersion；
4. Agent 只能产生 Candidate，Authority 才能 Commit；
5. 所有模型、CLI 和外部动作经过 Production Execution Gateway；
6. 所有生产上下文冻结并保留 ActualSentContext；
7. 已发布历史不可静默重写；
8. Canon 与 StoryState 分离，状态通过 Reducer 推进；
9. 正式状态修改必须绑定 Authority Decision；
10. Fixture、集成、真实 Provider、长篇和生产证明分级管理。

### ADR 生命周期

```text
PROPOSED → ACCEPTED → ACTIVE → SUPERSEDED → RETIRED
```

不得删除已生效 ADR；替代时必须记录 supersedes/superseded_by。

## 2. 实施范围

### 2.1 ADR 模板

每份 ADR 必须包含：

- Context；
- Decision；
- Scope；
- Alternatives；
- Consequences；
- Enforcement；
- Migration；
- Exceptions；
- Evidence；
- Supersession。

### 2.2 例外机制

架构例外必须形成有期限的 Exception Record：

```text
exception_id
adr_id
owner
scope
reason
risk
mitigation
expires_at
removal_issue
```

禁止“临时兼容”无限期存在。

### 2.3 变更审查

以下变更必须触发 ADR 检查：

- 新建 Authority 或正式 Writer；
- 新增任务状态机、Retry、Lease、Fence；
- 新增资产版本或审批语义；
- 新增模型/平台直连；
- 新增 LocalStorage 正式写路径；
- 修改 Plan hierarchy、StoryState、ContextManifest；
- 修改公共 API/Event；
- 修改生产身份、权限或部署拓扑。

## 3. 代码与文档位置

### 目标文档

- `docs/adr/README.md`
- `docs/adr/0002-postgresql-production-authority.md`
- `docs/adr/0003-single-command-kernel.md`
- `docs/adr/0004-unified-asset-version.md`
- `docs/adr/0005-agent-candidate-authority-commit.md`
- `docs/adr/0006-production-execution-gateway.md`
- `docs/adr/0007-frozen-context-and-actual-sent-context.md`
- `docs/adr/0008-immutable-published-history.md`
- `docs/adr/0009-canon-story-state-and-reducer.md`
- `docs/adr/0010-authority-decision-required.md`
- `docs/adr/0011-evidence-maturity-levels.md`

现有 `docs/adr/0001-stdlib-unittest-first.md` 保留，不重编号。

### 目标代码

- `src/novel_forge/core/architecture_policy.py`
- `src/novel_forge/core/architecture_exceptions.py`
- `scripts/architecture/check_adr_coverage.py`
- `tests/architecture/test_adr_enforcement.py`
- `.github/CODEOWNERS`
- `.github/pull_request_template.md`

### 禁止做法

不得把所有规则放入一个巨大配置文件；ADR 负责决策，代码策略对象负责可执行约束，Fitness Tests 负责验证。

## 4. 迁移脚本设计

本工作包通常不新增业务 migration。若架构例外需要持久化为 Authority 记录，应在 AC-19 评估后增加：

```text
architecture_policy_exceptions
architecture_policy_exception_events
```

但首阶段优先使用版本化 YAML/Markdown 和 CI，避免为纯治理提前扩充生产 schema。

非 SQL 脚本：

- `scripts/architecture/generate_adr_index.py`
- `scripts/architecture/check_adr_links.py`
- `scripts/architecture/check_adr_required_for_diff.py`

`check_adr_required_for_diff.py` 根据变更路径和语义标记 PR 是否必须更新 ADR。

## 5. 实施计划

1. 整理现有代码事实和历史设计，生成 ADR 草案。
2. 逐项评审决策、替代方案和兼容范围。
3. 为每份 ADR 指定代码 Owner 和 Fitness Test。
4. 将 ADR index 加入 `docs/README.md` 和 Claude Code 必读顺序。
5. 在 PR 模板中加入 Architecture Impact、ADR、Migration、Rollback、Evidence 字段。
6. 增加 CI 检查：ADR 编号、链接、状态、supersession、例外到期。

## 6. 测试矩阵

| 测试 | 场景 | 通过条件 |
|---|---|---|
| ADR schema | 缺少 Decision/Enforcement | CI 失败 |
| Numbering | 重复编号或断裂引用 | CI 失败 |
| Link check | supersedes 指向不存在文件 | CI 失败 |
| Diff policy | 修改 Authority ownership 无 ADR | CI 失败 |
| Exception expiry | 已过期例外 | CI 失败或阻止 release |
| Code mapping | ADR 未绑定测试/owner | CI 失败 |
| Negative | 新增直接 Provider 调用 | 触发 ADR/Fitness 失败 |

## 7. Acceptance Gate

```text
core_adrs_accepted=true
adr_index_generated=true
adr_code_owner_mapped=true
adr_fitness_test_mapped=true
architecture_exception_policy_active=true
pr_architecture_impact_check_active=true
```

必须至少完成十项核心 ADR 的 `ACCEPTED` 状态，并在 CI 中证明关键违规会失败。

## 8. 风险与控制

- ADR 过度形式化：只对不可逆、跨域和长期决策强制 ADR。
- 文档与实现脱节：每份 ADR 必须绑定测试和代码路径。
- 例外泛滥：例外必须有 Owner、到期日和删除任务。
- ADR 阻塞开发：提供轻量 Proposal 模板，但不能绕过生产边界。