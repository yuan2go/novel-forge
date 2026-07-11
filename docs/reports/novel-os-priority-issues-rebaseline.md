# Novel OS 16 项优先问题重基线

> 重基线日期：2026-07-11  
> 分支：`feat/v7-content-intelligence-and-longform-proof`  
> 代码基线：`f66ebb7` 加当前工作区未提交修改  
> 原则：代码、测试和运行结果优先；历史审计只作为检查索引。

## 1. 当前工作区事实

当前工作区在重基线开始前已经包含用户或其他工作留下的修改：

```text
M docs/README.md
M docs/reports/module-maturity-matrix.md
M docs/reports/next-production-slices.md
M docs/reports/v1-v7-roadmap.md
M scripts/run_v1_chapter_sequence_acceptance.py
M tests/unit/test_v1_chapter_sequence_acceptance_script.py
?? docs/plans/
?? docs/reports/novel-os-final-blueprint-gap-analysis.md
```

本报告不将这些改动回退、覆盖或自动认定为已发布能力。

## 2. 测试与验证基线

| 检查 | 结果 | 证据 |
|---|---|---|
| Python 全量测试 | **未通过**：779 tests，7 failures，35 errors，2 skipped，耗时 496.038s | `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'` |
| Workspace validation | **未通过**：3 个无项目归属运行资产 | `make validate` |
| Python compile/lint | 通过 | `make lint` |
| Web TypeScript check | 通过 | `npm --prefix web/admin run lint` |
| Web tests | 11 通过，1 个 Playwright smoke 跳过 | `npm --prefix web/admin test` |
| Skill drift | 通过 | `make check-skills` |
| Diff whitespace | 通过 | `git diff --check` |

当前 Python 失败主要聚为四组：

1. Source Governance Runtime Gate 接入后，旧 Context、发布和 Scheduler 夹具缺少合格来源证据，产生大量 fail-closed error；
2. `project_metric_snapshot` 缺少必填 `project_id`；
3. 项目隔离增强后，旧 Pipeline 产生跨项目 lineage 或无归属 Agent Registry 资产；
4. protagonist agency 等质量规则升级后，旧 12 章及章节序列期望仍把被阻断运行视作成功。

这些失败不能通过关闭 Gate、吞异常或降低阻断标准处理；需要迁移调用方、夹具、项目归属和验收语义。

## 3. 16 项问题当前状态

状态口径：`complete`、`partial`、`skeleton`、`missing`、`regressed`、`replaced`、`blocked`、`evidence-insufficient`。

| Issue | 当前状态 | 代码证据 | 测试证据 | 剩余缺口 | 是否需要实施 |
|---:|---|---|---|---|---|
| 1. 绿色回归和清洁工作区 | **complete** | Scope审计已修复历史system runtime资产；Production Context和Chapter Plan保持直接project scope | Python两轮781 pass/2 skip；`make validate`两轮通过；lint/type/skills/web/diff通过 | Playwright、在线后端和真实Provider属于独立证据层，不计入确定性绿色 | 否；保持回归门禁 |
| 2. ExecutionEnvelope 和核心引用 | **partial** | v2 canonical refs、legacy adapter、correlation/causation和stable idempotency位于`modules/os_envelope/service.py` | 17项Envelope/Loop/API兼容测试通过 | 未成为工业模式权威持久对象；Workflow/Agent/Loop入口覆盖仍不完整 | 是 |
| 3. 唯一 Production Kernel | **partial→completed（本地入口）** | `production_kernel.dispatch_production_operation`统一路由Chapter/Workflow/Agent/Loop；各Run仍分别为状态权威 | Kernel/Entrypoint/API/Loop/Workflow/Scheduler聚焦测试通过 | 工业authority和跨进程投递仍未完成；不能宣称全部运行时已工业化唯一 | 仅工业存储部分仍需实施 |
| 4. 移除固定 Topic/World/Character | **complete** | Topic/World/Character由Material/Topic/World项目资产派生并继承scope | 双目标差异化与生产治理共26项测试通过 | Draft fallback与demo/fixture全仓隔离留给后续专门工作包 | 否；保持防回归测试 |
| 5. Context 和来源门禁迁移 | **partial** | `context_builder/service.py` fail-closed；合法fixture通过SourcePolicy/Risk/clean sweep进入生产链 | Context/Publish/Scheduler/Analysis及全量回归均通过，非法来源负例仍阻断 | 仍需在Phase 1证明所有生产入口唯一经过Context Builder，并建立绕过契约扫描 | 是，剩余为入口覆盖而非回归修复 |
| 6. 资产完整性与内容质量分离 | **partial→completed（Gate契约）** | 两个独立GateResult各自有`gate_kind`/`gate_result_path`；内容质量不再复用资产完整性字段；生产Release evidence强制两者 | 发布/质量聚焦套件通过；重复、空正文、伪造ready绕过和新Gate字段均有测试 | Golden/Human Calibration、真实Provider趋势和平台质量仍未完成 | 质量闭环仍需实施，但不重做双Gate基础 |
| 7. 写放大和全目录扫描 | **partial→completed（运行时预算）** | `LocalStorage.write_budget`统计file/asset/bytes/scans/context builds；Chapter Kernel可在超预算时结构化失败 | WriteBudget/Kernel 8项通过；超预算在下一次写前失败且不产生越界文件 | 现有历史扫描尚未全量索引化；默认阈值需由10章Provider验收校准 | 是，性能基线和索引化仍需实施 |
| 8. typed StateEvent/Snapshot/reducer | **skeleton→partial** | StateEvent支持领域引用、evidence/confidence/causation/correlation/schema；longform reducer按Character/Timeline/Canon/Foreshadow/Arc/WorldRule等分桶；Snapshot/Replay有确定性`state_hash` | StateBus/Schema/OS能力29项通过；typed payload缺失、重放一致性和冲突仍有测试 | 仍需事件Schema迁移、accepted-chapter主链接入和人工修正/冲突记录 | 是，但继续整合现有State Bus |
| 9. Golden Dataset/Human Calibration | **partial** | `evaluation_center/service.py` 已有 human annotation、golden set、calibration readiness；现已增加`human-calibration-v1`、多标注者共识、agreement、verdict和版本化阈值推荐，并可生成带`calibration_ref`的新Rubric | `test_quality_eval_v2.py` 覆盖双标注者一致性、MAE、阈值推荐和校准Rubric版本绑定 | 仓库仍无真实Provider多题材Golden基线；当前阈值是小样本建议，尚未成为10/30章生产验收证据 | 是，下一步接入真实Provider并扩大人工校准集 |
| 10. 10/30 章真实 Provider 验收 | **evidence-insufficient** | 有 Mock/确定性章节和 long-chain proof；README 支持 opt-in Provider | 当前 10 章证据为 artifact coverage 且正文重复；无 30 章真实内容报告 | 缺预先定义 Rubric、预算、真实 Provider 运行、人工评审和失败报告 | 是，依赖 1-9/11 |
| 11. 服务端验证 ApprovalRequest | **partial→completed（发布边界）** | `verify_approval_request`服务端检查status/scope/action/project/expiry/revoke/consume和目标digest；Adapter与human override调用verifier | Permission/Publishing 9项覆盖stale、wrong-scope、expired、revoked、replay和消费 | 全局旧调用方仍需迁移到verifier；RBAC/审批人资格和所有非发布副作用仍待安全硬化 | 是，继续扩展调用面 |
| 12. 发布 Adapter/Receipt/Compensation | **partial** | `publishing/adapters.py` 与 `publishing_feedback_adapters/` 各有路径；后者有 `PlatformPublishReceipt` 和失败记录 | 发布和平台 Adapter 测试存在，但当前部分被 Source Gate 阻断 | 两套契约未合并；真实平台仍是 manual profile；receipt/idempotency/compensation 状态语义未统一 | 是 |
| 13. Goal Planner/recurring controller | **missing** | Scheduler 有 lease、retry、dead-letter、checkpoint、budget；未发现受限 GoalPlan/PlanVersion 控制器 | Scheduler 局部测试充分，Planner/recurring 目标级测试缺失 | 仍是 A2 有界执行器；缺目标分解、计划版本、stop/takeover/cooldown/missed-run | 是，必须后于 Kernel/State/Eval/Storage |
| 14. Source/Canon/Eval/Portfolio 深度控制台 | **partial** | Web Admin 有相关路由和工作台；Backend 有 Source、Canon、Eval、Portfolio API | Web 静态架构测试通过；Playwright 未安装而跳过 | 部分页面偏通用资产编辑/证据展示；缺冲突解决、回放、标注校准和真实浏览器 E2E | 是，依赖后端治理能力 |
| 15. 工业存储权威和事务 Outbox | **missing→partial（Local垂直切片）** | 新增`outbox_event` typed asset，支持幂等enqueue、claim、ack、failed；StateEvent写入后产生可追踪Outbox证据；AgentOutbox仍仅为消息盒 | StateBus/Schema/OS能力29项覆盖Outbox claim/ack/idempotency | Postgres事务UoW、DB/Artifact双写失败注入、投影重放和工业authority仍未建立 | 是；必须在自治恢复和真实Provider前完成 |
| 16. 三书并行、CI、安全和 DR | **partial** | Portfolio 计划/隔离组件、Docker、部分安全守卫和本地 failure drill 存在；自动 dispatch 明确关闭 | 项目隔离测试局部存在；当前工作区隔离校验失败；Playwright 跳过 | 缺三书真实并行、分层 CI、RBAC/Secrets/安全套件和全存储 restore rehearsal | 是，最后阶段 |

## 4. 与旧审计相比的状态变化

旧审计中的主要方向仍成立，但以下能力不能再简单描述为“完全缺失”：

- Issue 8：已有通用 State Bus、Snapshot、Replay 和 Canon typed reducer 局部实现，当前问题是领域语义、主链权威和可迁移性不足；
- Issue 9：Evaluation Center 已有 Golden Set/Human Annotation first slice，当前问题是没有生产数据和人工校准证据；
- Issue 12：已有 Receipt 类型和发布失败记录，当前问题是两套 Adapter 分裂且补偿契约不统一；
- Issue 14：已有较广 UI 路由，当前问题是治理深度和浏览器级证据不足。

以下旧问题仍被当前运行结果直接证实：

- Issue 1 和 5 已处于回归状态；
- Issue 3 的多执行平面仍存在；
- Issue 4 的固定 World/Character 仍在生产服务；
- Issue 10 没有真实 10/30 章内容证据；
- Issue 15 没有事务 Outbox；
- Issue 16 的项目隔离基础当前仍失败。

## 5. 当前依赖结论

根据当前代码，建议的真实依赖顺序维持为：

```text
Phase 0：恢复绿色和项目隔离
  -> Envelope 最小协议 + Production Kernel tracer bullet
  -> fixture 隔离 + Context/Source 迁移 + 质量语义分离
  -> 写入/扫描预算
  -> 领域 StateEvent/Snapshot + 工业 authority/transactional outbox
  -> Golden/Human Calibration + 服务端 Approval verifier
  -> 真实 Provider 10/30 章
  -> 统一 Release Adapter
  -> Bounded Planner/Recurring Controller
  -> 深度治理 UI
  -> 三书并行、CI、安全、DR
```

Issue 15 必须在真实长篇自治恢复之前完成，但不应在 Local 模式单章 Kernel 建立前引入全量工业基础设施。

## 6. 是否可进入实施

Phase 0已经以两轮确定性全量绿色关闭，可以进入 **Phase 1 Envelope与Production Kernel收敛**。真实Provider、自治和工业存储仍不得提前，必须先取得生产入口覆盖、单一状态权威与绕过测试证据。
