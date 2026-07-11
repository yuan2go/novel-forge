# Novel OS Phase 0 可信工程基线设计

## 1. 目标

在不降低 Source、Context、ReviewIssue、Approval 或质量门禁的前提下，将当前确定性工程基线从：

```text
779 tests / 7 failures / 35 errors / 2 skipped
workspace validation: 3 unscoped runtime assets
```

恢复为可重复、可解释的绿色基线，为 ExecutionEnvelope 和 Production Kernel 收敛提供稳定起点。

本阶段不实现新生产协议、不引入第五套执行状态、不运行真实付费 Provider，也不把历史 Mock/fixture 证据升级为内容质量证据。

## 2. 设计选择

采用“严格止血”方案：先按共同根因修复回归，再进入架构演进。

不采用以下方案：

- 一边修测试一边重构 Kernel：会混淆 Gate 迁移错误和新协议错误；
- 跳过失败直接建设 Envelope：会在红色基线上长期保留新旧两套协议；
- 关闭或放宽 Gate：会把不可信输入重新带回生产路径。

## 3. 工作包边界

### WP-00A：失败清单和可重复基线

- 固定本地确定性验证命令；
- 将 Python、Web、workspace、Skill、lint 结果写入进度报告；
- 将外部数据库、真实 Provider、浏览器 E2E 明确标记为独立测试层；
- 不把 Playwright 跳过解释为全量 UI 绿色。

### WP-00B：Source Gate 合法夹具迁移

- 找到 35 个 error 中共享的三条 blocking source-governance rows 来源；
- 修复测试工作区或生产就绪夹具，使合法测试资产具有真实 SourcePolicy、SourceRiskReport、eligibility/lineage 证据；
- 保留 raw/high-risk/stale/quarantined 负例的 fail-closed 行为；
- 改进错误定位，但不捕获后继续生成。

### WP-00C：项目隔离和运行资产归属

- 修复 workflow definition、scheduler lease 和 Agent Registry 等 system/runtime 资产的 scope 语义；
- 项目资产必须绑定 `project_id`；真正的系统级资产必须绑定明确 system workspace，而不是保持无归属；
- 修复旧 Pipeline 中跨项目 lineage 的引用创建方式；
- 历史 `.local/workspace` 资产采用可审计隔离/迁移，不静默绑定任意小说项目。

### WP-00D：质量门禁与旧验收语义

- protagonist agency 等新增规则继续阻断不合格内容；
- 更新旧测试输入，使“应成功”样本真正达到规则要求；
- 对专门验证阻断的样本更新期望为失败和 ReviewIssue 证据；
- 不通过降低阈值或删除断言制造绿色。

### WP-00E：证据语义和基线完成

- 明确 artifact coverage、deterministic proof、sandbox integration、real-provider acceptance 四种证据；
- 当前 10 章 fixture 只证明工作流和资产完整性；
- 运行完整确定性套件至少两次，确认结果可重复；
- 更新重基线、执行进度、测试说明和当前状态文档。

## 4. 数据和控制流

```text
测试/生产就绪夹具
  -> 创建明确 Project/System Scope
  -> 创建合法 Source/Policy/Risk/Eligibility 证据
  -> Context Builder
  -> Source Runtime Gate (fail-closed)
  -> Workflow/Agent/Publishing operation
  -> ReviewIssue/Quality Gate
  -> 断言成功或受控阻断
```

任何成功样本都必须通过同一门禁链，不允许测试专用 bypass。测试可以使用确定性 Provider，但必须显式标记为 fixture/mock，不能生成 release-ready 的真实 Provider 声明。

## 5. 错误处理

- Gate 失败保留稳定错误码或可定位消息；
- 合法夹具缺证据时测试失败，不自动补 trusted 标记；
- 非法来源负例继续硬停；
- 项目 scope 冲突不自动改写 lineage；
- 质量阻断返回 ReviewIssue 和恢复建议；
- 每次修复优先改共享 fixture builder 或领域入口，避免在数十个测试中复制补丁。

## 6. 测试策略

每个共同根因先增加或收紧一个聚焦回归，再修改实现/夹具：

1. Source Gate：合法来源通过、缺证据失败、高风险失败；
2. Project Scope：项目资产、系统资产、跨项目引用、无归属资产；
3. Quality Gate：合格 protagonist agency 通过，不合格样本阻断；
4. Pipeline：sample run 在临时空工作区中无跨项目引用；
5. Workspace：当前 workspace 和干净 workspace 分别验证；
6. 完整套件：Python、Web、lint、type、skills、diff check。

真实 Provider、Postgres/MinIO/Qdrant、Playwright 和长篇压力测试在报告中单列，Phase 0 不伪装为已执行。

## 7. 完成标准

- Python 确定性测试 0 failure、0 error；
- Web 静态/Node 测试通过，浏览器测试状态明确；
- `make validate` 通过且无无归属运行资产；
- lint、type check、Skill drift、`git diff --check` 通过；
- Source/Context/Quality Gate 的负例仍 fail-closed；
- 连续两次完整确定性验证得到相同结果；
- 进度文档记录每个失败根因、修复和测试证据。

## 8. 范围外

- ExecutionEnvelope v2；
- Production Kernel 状态统一；
- typed novel-domain StateEvent；
- transactional Outbox；
- Golden 生产数据；
- 真实 Provider 10/30 章；
- Goal Planner、发布统一和三书并行。

它们保留在16项总计划中，并在 Phase 0 绿色后按依赖继续。

