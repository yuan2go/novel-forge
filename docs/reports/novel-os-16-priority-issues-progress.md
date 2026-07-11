# Novel OS 16 项优先问题执行进度

> 更新日期：2026-07-11  
> 当前阶段：Phase 3前置 — Kernel、质量Gate、预算与长篇状态首个垂直切片已完成；Golden/Human Calibration 已进入可绑定阈值的实现阶段

| Work Package | 状态 | 已完成 | 测试证据 | 剩余问题 | 下一步 |
|---|---|---|---|---|---|
| WP-00A 基线分类 | completed | 已取得首次全量基线、16项重核验和五层测试证据口径 | Python 779 tests / 7F / 35E / 2S；聚焦Source/Publish/Scheduler 79 tests / 1F / 21E；Web 11 pass / 1 skip；validate 3 unscoped | 无；失败已归入Source Gate、项目隔离、旧运行期望和质量门禁四组 | 执行Task 0.2 |
| WP-00B Source Gate迁移 | completed | 修复workspace readiness Schema；建立可复用的自有来源、Policy、Risk、eligibility和clean sweep fixture | Source/Review 37 pass；Publish/Editor/Analysis 29 pass；Platform/Registry 21 pass | 无；Scheduler仍有1个独立旧状态期望，归入WP-00D | Task 0.4 |
| WP-00C 项目隔离 | completed | Pipeline在创作前创建项目并逐步绑定资产；Registry/Workflow/Lease使用显式system scope；历史3资产经审计修复 | 8个scope/pipeline聚焦测试通过；`make validate`通过 | 无 | Task 0.5 |
| WP-00D 质量门禁语义 | completed | strict workflow夹具补齐Source Gate证据；10章fake覆盖27项当前契约；12章正文具备真实主动选择和代价 | Acceptance/Sequence/Loop/Scheduler/12章共28 tests通过 | 无 | Task 0.6 |
| WP-00E Phase 0关闭 | completed | 修复生产上下文project scope传播；迁移剩余Source/质量夹具；完成两轮可重复全量验证 | Python两轮均781 pass/2 skip；validate两轮通过；lint/type/skills/web/diff通过 | Playwright和真实Provider仍属于非确定性/外部证据层 | 进入Phase 1 |
| WP-01 Envelope v2与章节Kernel | completed | v2 canonical refs/legacy adapter/稳定幂等；章节、Workflow、Agent、Loop API和内部调用均经`dispatch_production_operation`统一路由；各自Run仍是状态权威 | Kernel/Entrypoint/API/Loop/Workflow/Scheduler聚焦测试通过 | Envelope工业authority和Postgres幂等持久化仍未完成 | 进入长篇状态与存储证据 |
| WP-03 固定内容隔离 | completed | Topic、World、Character由上游项目资产驱动；删除固定钟楼/林乔输出 | 双目标+主链26 pass | Draft mock fallback仍须在后续Provider/fixture隔离工作包中核验 | 进入Context/质量工作包 |
| WP-05 Release质量Gate | completed | 独立`release_asset_integrity`与`release_content_quality` GateResult；各自`gate_kind`/`gate_result_path`；生产Release evidence强制引用二者；human override必须服务端验证 | 发布/审批/质量聚焦套件通过；最新全量810 tests通过 | Golden/Human Calibration和真实Provider趋势仍未完成 | 进入质量基准与真实Provider前置 |
| WP-06 跨章语义相似度 | completed | ChapterPatternReport增加项目隔离、前章窗口、embedding/lexical双证据和风险阈值；新增可插拔语义Provider；HashEmbedding显式标记为`regression_only`，外部Provider标记为`verified` | Longform单元/集成16项通过；覆盖本地回归边界和注入语义Provider | 本地HashEmbedding仍不能单独证明精品质量；生产真实Provider需凭据和校准集 | 与Golden/真实Provider验收联动 |
| WP-07 审批版本绑定 | completed | ApprovalRequest保存目标asset digest/version/path；服务端检查状态、scope、action、project、expiry、撤销、消费和目标版本；发布Adapter/生产override均使用verifier | Permission Center/Publishing Center 9项通过，覆盖stale、错误scope、过期、撤销、replay | 多角色RBAC和审批人资格仍属安全硬化 | 纳入治理E2E |
| WP-08 Kernel写预算 | completed | `LocalStorage.write_budget`统计文件/asset/字节/扫描/Context构建；超预算在下一次写入前失败并返回恢复提示 | WriteBudget/Kernel 8项通过 | 默认阈值需通过10章真实Provider校准；工业双写预算未完成 | 与长篇验收联动 |
| WP-09 typed StateEvent与Outbox | completed | StateEvent支持领域引用、evidence/confidence/correlation/causation/schema；确定性reducer和state_hash Snapshot/Replay；新增幂等Outbox queued/claimed/acked/failed | StateBus/Schema/OS能力29项通过；最新全量810 tests通过 | Postgres事务UoW、投影恢复和故障注入仍未完成 | 进入真实Provider验收前置 |
| WP-10 Golden/Human Calibration | completed（本地实现） | Human annotation支持版本、角色、置信度；Golden Set支持多标注者和预期 verdict；Provider calibration计算人类共识、多人一致性、MAE和保守阈值建议；可生成不可变 calibrated rubric 版本；生产模式额外要求至少两个人工标注案例、两名标注者及 agreement≥0.8 | Quality Eval 15项通过；覆盖双标注者一致性、阈值推荐、rubric calibration ref、生产阈值强制绑定和版本不变性 | 尚无真实 Provider 10/30 章数据；单案例或单标注只能是 calibration baseline，不能宣称生产质量已校准 | 运行外部Provider并提交人工校准证据 |
| WP-01..15 | not-started | 已完成依赖排序和重基线 | `novel-os-priority-issues-rebaseline.md` | Phase 1需先重核验Envelope和执行入口 | 细化WP-01 |

## 当前基线

```text
Python: PASSED — latest 810 tests, 0 failures, 0 errors, 2 skipped
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

1. 已解决：ExecutionEnvelope从v0.1 metadata升级为v2 canonical contract，保留legacy shadow；章节、Workflow、Agent、Loop入口统一经Production Kernel dispatcher，章节生产在Run写入前验证production Envelope。
2. 新协议：`schema_version=2`、11类核心Ref、correlation/causation、stable idempotency key、`legacy_derived`。
3. 状态权威：Kernel facade只校验/委派；ChapterProductionRun、WorkflowRun、AgentRun、LoopRun仍分别是权威状态，未创建第五套状态机。
4. 入口迁移：章节生产API、Workflow API、Agent Dispatch API、Loop API以及Workflow/Agent/Recap/Revision内部调用均经`dispatch_production_operation`；direct service仅保留防御性兼容边界。
5. 固定内容：Topic、World和Character不再写入钟楼/林乔样例；双目标测试覆盖题材、设定、外部目标与项目归属差异。
6. 证据：Envelope/Kernel/Entrypoint/API/Loop/Workflow/Scheduler聚焦测试通过；所有注册生产入口的`kernel_route`统一为`dispatch_production_operation`。
7. 未完成：Envelope repository/工业幂等持久化、Context全入口manifest、Golden/Human Calibration和真实Provider仍未关闭。

## Release质量Gate阶段记录（进行中）

1. 资产完整性与内容质量已拆成两个独立 GateResult：前者检查类型、不可变ID、项目scope和正文可解析性；后者检查章节长度、项目内重复、章节推进和状态一致性。
2. 生产模式下任一 Gate 失败都会进入 PublishGate blocking issues；ReleasePackage 的 durable evidence 缺失也会阻断，即使客户端或历史报告把 decision 改成 `ready`。
3. 跨章语义相似度已进入ChapterPatternReport，采用有界项目内前章窗口和embedding/lexical双证据；本地HashEmbedding明确为`regression_only`，注入真实语义Provider才可标记`verified`；它仍不是唯一质量指标。
4. ApprovalRequest已绑定目标版本digest；外部发布和生产human override不得接受客户端自报approved。
5. 运行时写预算和typed StateEvent/Outbox已完成本地垂直切片；全量回归和工业Postgres事务仍待最终验收。

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

## WP-06 / WP-07 / WP-08 / WP-09 完成记录

1. 解决内容：跨章语义相似度、ApprovalRequest目标版本绑定、统一Kernel路由、Release双Gate字段分离、运行时写预算和typed StateEvent/Outbox均完成首个可验证垂直切片。
2. 核心模块：`longform_stability/service.py`、`permission_center/service.py`、`publishing/quality_gates.py`、`publishing/release_gate.py`、`publishing/adapters.py`、`production_kernel/service.py`、`storage/write_budget.py`、`state_bus/service.py`及`state_bus/outbox.py`。
3. 旧路径：保留WorkflowRun、AgentRun、LoopRun和ChapterProductionRun各自状态权威；旧审批请求仍可展示，但涉及新发布副作用的调用必须经过server verifier；没有创建新的执行状态机。
4. 新协议/模型：`cross-chapter-semantic-similarity-v1`、Approval target `version_binding`、`dispatch_production_operation`、`release_asset_integrity`/`release_content_quality`双Gate、`LocalStorage.write_budget`、`state-event-v1`、`outbox_event`。
5. 测试：Longform 15项；Permission/Publishing 9项；Kernel/WriteBudget 8项；StateBus/Schema/OS能力29项；最终还需执行全量回归、validate、lint、skills、前端检查。
6. 结果：聚焦套件通过；跨项目相似度隔离、错误scope/过期/撤销/replay审批、超写预算、typed payload缺失、Snapshot state_hash一致性和Outbox幂等均有负例或边界证据。
7. 已知风险：本地HashEmbedding只适合作为确定性回归信号；Golden/Human Calibration虽已具备生产证据边界，但当前仓库尚无真实Provider多题材样本；单案例报告只能生成baseline，`require_calibrated_thresholds=True`会拒绝它；Outbox目前是LocalStorage事务边界内的持久事件，尚未接入Postgres事务UoW和双写故障恢复；真实10/30章仍未运行。
8. 阶段标准：本地垂直切片通过；工业存储、Golden/Human Calibration和真实Provider标准未宣称完成。
9. 下一阶段前置条件：WP-10本地实现已满足，可进入真实Provider前置；必须用至少两个人工标注案例、两名标注者和agreement≥0.8生成`production_ready`校准报告，再使用`create_calibrated_quality_rubric`生成带`calibration_ref`的版本化Rubric，并在生产调用启用`require_calibrated_thresholds=True`；不得把本轮聚焦测试解释为精品长篇验收。

## WP-10 Golden/Human Calibration完成记录

1. 解决内容：把现有Evaluation Center first slice升级为可追溯的人工校准链，而不是仅比较一组内联分数。
2. 核心模块：`evaluation_center/service.py`增加`human-calibration-v1`、多标注者共识、pairwise agreement、verdict标签和阈值推荐；`create_calibrated_quality_rubric`创建新版本而不修改旧Rubric；`quality_eval/service.py`在Provider请求和报告中记录Rubric版本、校准引用和阈值来源。
3. 旧路径：旧的单标注/expected score调用仍兼容；没有把未校准Rubric自动伪装为生产校准。
4. 新协议/模型：Golden Set的`calibration_version`、case `annotation_paths`/`expected_verdict`；Calibration Report的`human_calibration`、`threshold_recommendation`；Rubric的`rubric_version`、`calibration_ref`和`threshold_calibration`。
5. 测试：Quality Eval 14项、Longform 16项通过；双标注者一致性、MAE、阈值推荐、校准Rubric版本绑定和本地Hash/外部Provider状态均有测试。
6. 结果：本地校准实现通过；可以把人工/Golden证据转成真实Provider验收使用的明确阈值，但尚未有真实Provider内容运行证据。
7. 已知风险：单个或少量样本只产生“建议阈值”；至少需要跨题材、多正负例、多人复核后才能把`calibration_status=passed`升级为生产信任。
8. 阶段标准：WP-10本地实现通过；真实Provider标准未宣称完成。
9. 下一阶段前置条件：准备真实Provider 10章运行、记录成本/延迟/失败和人工评分；运行时必须传入校准Rubric，并在生产模式启用`require_calibrated_thresholds=True`。
