# Novel OS 16 项优先问题执行进度

> 更新日期：2026-07-11  
> 当前阶段：Phase 1 — 统一生产执行内核（WP-01 / WP-03进行中）

| Work Package | 状态 | 已完成 | 测试证据 | 剩余问题 | 下一步 |
|---|---|---|---|---|---|
| WP-00A 基线分类 | completed | 已取得首次全量基线、16项重核验和五层测试证据口径 | Python 779 tests / 7F / 35E / 2S；聚焦Source/Publish/Scheduler 79 tests / 1F / 21E；Web 11 pass / 1 skip；validate 3 unscoped | 无；失败已归入Source Gate、项目隔离、旧运行期望和质量门禁四组 | 执行Task 0.2 |
| WP-00B Source Gate迁移 | completed | 修复workspace readiness Schema；建立可复用的自有来源、Policy、Risk、eligibility和clean sweep fixture | Source/Review 37 pass；Publish/Editor/Analysis 29 pass；Platform/Registry 21 pass | 无；Scheduler仍有1个独立旧状态期望，归入WP-00D | Task 0.4 |
| WP-00C 项目隔离 | completed | Pipeline在创作前创建项目并逐步绑定资产；Registry/Workflow/Lease使用显式system scope；历史3资产经审计修复 | 8个scope/pipeline聚焦测试通过；`make validate`通过 | 无 | Task 0.5 |
| WP-00D 质量门禁语义 | completed | strict workflow夹具补齐Source Gate证据；10章fake覆盖27项当前契约；12章正文具备真实主动选择和代价 | Acceptance/Sequence/Loop/Scheduler/12章共28 tests通过 | 无 | Task 0.6 |
| WP-00E Phase 0关闭 | completed | 修复生产上下文project scope传播；迁移剩余Source/质量夹具；完成两轮可重复全量验证 | Python两轮均781 pass/2 skip；validate两轮通过；lint/type/skills/web/diff通过 | Playwright和真实Provider仍属于非确定性/外部证据层 | 进入Phase 1 |
| WP-01 Envelope v2与章节Kernel | in-progress | v2 canonical refs/legacy adapter/稳定幂等；章节API、Scheduler、Workflow经同一facade；Bus在Run写入前fail-closed | Envelope/Loop/API 17 pass；Kernel/API/Scheduler/Workflow 101 pass | Envelope尚未持久化为工业authority；Workflow/Agent/Loop仍为compat_pending入口 | 扩大入口覆盖并核验状态权威 |
| WP-03 固定内容隔离 | completed | Topic、World、Character由上游项目资产驱动；删除固定钟楼/林乔输出 | 双目标+主链26 pass | Draft mock fallback仍须在后续Provider/fixture隔离工作包中核验 | 进入Context/质量工作包 |
| WP-05 Release质量Gate | in-progress | 独立`release_asset_integrity`与`release_content_quality` GateResult；生产Release evidence强制引用二者 | 发布/隔离/自动Gate 22 pass；重复正文、空正文和伪造ready绕过均阻断 | 尚未覆盖跨章相似度、人工Approval版本绑定和真实Provider质量趋势 | 继续补齐ReviewIssue与人工审批契约 |
| WP-01..15 | not-started | 已完成依赖排序和重基线 | `novel-os-priority-issues-rebaseline.md` | Phase 1需先重核验Envelope和执行入口 | 细化WP-01 |

## 当前基线

```text
Python: PASSED twice — 781 tests, 0 failures, 0 errors, 2 skipped
Workspace validate: PASSED twice — 0 unscoped/cross-project runtime assets
Python compile: PASSED
Web TypeScript: PASSED
Web Node tests: PASSED — 11 passed, 1 Playwright skipped
Skill drift: PASSED
git diff --check: PASSED
```

## Phase 0完成报告

1. 解决内容：Source Gate迁移、项目/系统运行资产归属、质量夹具语义和生产上下文作用域传播均已恢复；没有关闭或放宽任何Gate。
2. 核心模块：Source readiness、Pipeline、Agent Registry、Workflow Definition、Runtime Ledger、Production Context、Chapter Plan，以及相应测试治理夹具。
3. 旧路径：sample Pipeline改为先创建项目再逐步生产；legacy system runtime资产通过scope audit修复；旧缺治理证据fixture被替换。
4. 协议/模型：workspace/system/project三类scope明确；Chapter Plan显式携带project/workspace；无新执行平面。
5. 测试：两轮`python3 -m unittest discover -s tests`；两轮`make validate`；`make lint`、`make check-skills`、前端TypeScript/Node、`git diff --check`。
6. 结果：第一轮781 tests in 634.854s，第二轮781 tests in 559.205s，均OK且仅2项显式外部测试跳过；辅助验证全通过。
7. 已知风险：Playwright未安装；在线后端、真实Provider和长链pressure仍按设计需显式opt-in，不能解释为已验证。
8. 阶段标准：Phase 0通过。
9. 下一阶段条件：已满足；进入Phase 1并先建立Envelope/Kernel入口事实图。

## Phase 1阶段记录（进行中）

1. 已解决：ExecutionEnvelope从v0.1 metadata升级为v2 canonical contract，保留legacy shadow；章节生产在任何ChapterProductionRun写入前验证production Envelope。
2. 新协议：`schema_version=2`、11类核心Ref、correlation/causation、stable idempotency key、`legacy_derived`。
3. 状态权威：Kernel facade只校验/委派；ChapterProductionRun、WorkflowRun、AgentRun、LoopRun仍分别是权威状态，未创建第五套状态机。
4. 入口迁移：章节生产API、Agent Scheduler和Workflow processor经`dispatch_chapter_production`；direct Bus保留防御性检查。
5. 固定内容：Topic、World和Character不再写入钟楼/林乔样例；双目标测试覆盖题材、设定、外部目标与项目归属差异。
6. 证据：17项Envelope兼容测试、101项Kernel路径测试、26项固定内容/生产治理测试均通过。
7. 未完成：Envelope repository/工业幂等持久化、Workflow/Agent/Loop全面迁移、Context全入口manifest、Release质量分离、写放大预算仍未关闭。

## Release质量Gate阶段记录（进行中）

1. 资产完整性与内容质量已拆成两个独立 GateResult：前者检查类型、不可变ID、项目scope和正文可解析性；后者检查正文完整性、项目内重复、章节推进和状态一致性。
2. 生产模式下任一 Gate 失败都会进入 PublishGate blocking issues；ReleasePackage 的 durable evidence 缺失也会阻断，即使客户端或历史报告把 decision 改成 `ready`。
3. 本阶段没有使用相似度单指标代表小说质量；重复检查目前采用规范化正文 hash，跨章语义相似度留给后续评测中心与人工校准。

## WP-00A 完成记录

1. 解决内容：建立当前分支而非历史报告的测试事实基线，并分开确定性、沙箱、浏览器、真实Provider和真实平台证据。
2. 核心模块：仅文档；未修改业务行为。
3. 旧路径：没有删除或兼容业务路径。
4. 协议/模型：没有新增运行协议。
5. 测试：Python全量、Source/Publish/Scheduler聚焦、Web Node、Web TypeScript、compile、Skill drift、workspace validate、diff check。
6. 结果：确定性基线未通过；聚焦套件确认21个error共享Source Gate前置证据缺失，另有1个Scheduler旧状态期望失败。
7. 风险：其他聚焦套件仍需在对应工作包复跑；浏览器E2E未执行。
8. 阶段标准：WP-00A通过；Phase 0未通过。
9. 下一阶段条件：已满足Task 0.2进入条件。

## WP-00B 完成记录

1. 解决内容：workspace级readiness不再违反Schema；合法production fixture不再因缺stale/retention/eligibility证据被Source Runtime Gate误阻断。
2. 核心模块：`source_intake/guarded_apply_readiness.py`；测试侧新增`source_governance_fixtures.py`。
3. 旧路径：没有增加bypass；未治理知识卡仍被生产Gate拒绝。
4. 协议/模型：workspace聚合报告使用`system:workspace`和`scope_kind=workspace`；项目报告保持真实project scope。
5. 测试：Source/Review、Publish、Agent Editor、Analysis、Publishing Adapter、Registry/Scheduler Integration聚焦套件。
6. 结果：87个聚焦测试通过；Agent Scheduler另有1个非Source Gate状态期望失败，留给WP-00D。
7. 风险：完整Python套件需在后续工作包后重跑；fixture helper只用于测试，不是生产信任捷径。
8. 阶段标准：WP-00B通过；Phase 0未通过。
9. 下一阶段条件：已满足Task 0.4进入条件。

## WP-00C 完成记录

1. 解决内容：sample pipeline不再事后批量猜测项目归属；系统Registry、Workflow Definition和Scheduler Lease不再保持无归属。
2. 核心模块：`workflows/pipeline.py`、`agent_registry/service.py`、`workflow_nodes/service.py`、`runtime_ledger/service.py`、`api/services/product.py`。
3. 旧路径：保留旧Pipeline兼容入口，但其sample流程现在先立项目再生产；历史system runtime资产由`project_scope_audit(repair=True)`显式修复。
4. 协议/模型：system runtime metadata统一为`project_id=local-system`、`workspace_path=local-system`、`scope_kind=system`。
5. 测试：Agent Registry、legacy system repair、Workflow Definition、Scheduler Lease和sample pipeline双运行。
6. 结果：8个聚焦测试通过；当前`.local/workspace`验证通过，0 unscoped/cross-project issue。
7. 风险：完整套件仍可能暴露其他创建器的scope问题；将在Task 0.6验证。
8. 阶段标准：WP-00C通过；Phase 0未通过。
9. 下一阶段条件：已满足Task 0.5进入条件。

## WP-00D 完成记录

1. 解决内容：strict Workflow成功样本补齐不可绕过的Source Gate引用；章节序列fixture迁移到27项当前输出契约；12章成功样本不再因主角无主动性被正确质量门禁阻断。
2. 核心模块：仅测试/验收fixture；没有降低`character_pressure`、ReviewIssue或Release Gate阈值。
3. 旧路径：旧19项artifact coverage fixture升级为27项；缺Source Gate的strict workflow不再被误当作可进入Scheduler。
4. 协议/模型：Workflow runtime policy显式引用`source_governance_runtime_gate_path`。
5. 测试：Novel OS acceptance、10章sequence、Loop Kernel、strict Scheduler budget和12章industrial pressure。
6. 结果：28个聚焦测试通过；低agency和缺Source Gate负例仍保持阻断。
7. 风险：12章仍是确定性pressure fixture，不是精品内容验收或真实Provider证据。
8. 阶段标准：WP-00D通过；Phase 0等待完整套件。
9. 下一阶段条件：已满足Task 0.6进入条件。
