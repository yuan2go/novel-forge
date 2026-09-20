# Real Provider Calibration Campaign：阶段证据与未达验收项

**本工作包未完整交付。** 本次完成了原生 Router / Kernel 的一组校准证据和预算隔离修复，没有执行真实校准、12 章生产、真实 Codex 升级或独立经济性比较。缺口同时涉及实现、授权、可信评价输入和统计证据；不能描述为“只差授权”。

## 版本与范围

- baseline / 开始时实际 origin/main：`feba06582b6cadf2e80f5c573cf427114cf2a926`
- baseline Git tree：`7fe1e48f3e7fe56666a5407f17c787b20c8c91c3`
- baseline implementation tree：`sha256:e1dd43acca11bcecbb7e736e65332fa8824e305e85e6fa1ab503ed103a560537`
- 最后实现 SHA（含回归测试）：`f5ba1faf058af2613f7116904a6230eac1f0e02c`
- canonical exact-SHA 门禁 tested SHA：`bbca0e7a4a0ed61381d0175272e9fe1763d7137a`
- 实现树：`sha256:2a0f369f4e29d34f5d56bbf9dcd9d0401c568c0188050d3a389640d95bbfb408`
- 实现/测试分支：`codex/real-provider-source-bootstrap-20260920`；交付证据分支：`codex/real-provider-campaign-delivery-20260920`。独立 worktree，原工作树和已有作品未覆盖。本会话未执行 push、建 PR 或 GitHub 合并；交付工作树只做了本地快进以包含当前实现。
- 执行期间远端状态发生变化：PR [#93](https://github.com/yuan2go/novel-forge/pull/93) 已于 2026-09-20 10:22:25 UTC 合入最初两条提交；远端分支为 `47094e01c23f53aa4a5ff9c89f395b126bf8d9b5`，最新 main 为 `19da636dae5d0b615bc22124f83908ff8af710ac`。main 的文件树与该早期提交一致，没有额外业务变更。最初远端两条提交之后的本地修复/文档提交包含本次 reference 入口；最终发布状态见 evidence index。
- 此报告所在的后续提交仅保留证据，不改变实现树。最终完整提交 SHA 由 Git 和最终回复给出，避免在提交自身内容中伪造自引用 SHA。

## 已实现的变更

文档清理先于业务代码独立提交（`2cd04a649aa9042f17470ae92d09263bd77de668`）：纠正真实 Provider 入口的排他描述、过期迁移上限和旧价格脚注。三个 proposal 都仍有未完成目标，没有为通过检查删掉目标或历史运行证据。受影响 proposal 已根据当前实现重新检查范围并绑定 SHA，仍保留 G3/G4 和 Memory B–E 缺口。

原生执行链仍为业务 Authority → `ProductionProviderRouter.select` → 冻结 `routing_decision` → Provider admission → Kernel 预算预留 / ExternalEffect → receipt / settlement → owning Authority → 原 benchmark 投影。未增加执行引擎、预算表或 benchmark 数据库。

1. `PROVIDER_ROUTING` 版本化策略校验历史授权不可变。Planning bootstrap 可附同一个 campaign 的 manifest、数据组、分区和总额度；Kernel 在原账本中跨授权累计。更换授权 ID、策略版本或 run key 不重置额度；未知外部结果仍要求先对账。
2. campaign 数据组和同一输入版本集合不能跨分区，相同输入版本集合不能通过换组名制造独立样本。语义重复、重新登记为新资产的相同内容仍需冻结数据集审查，不能仅靠这项哈希检查保证独立性。新授权不能丢弃已绑定的 campaign。当前单个 project 只能绑定一个 campaign 的限制是本实现范围的运行事实，不是永久产品架构结论。
3. Router v4 按 campaign 数据组首个观测（非 campaign 按 input hash）计算独立质量样本；重试保留成本和交付率。被窗口截掉首轮的重试不补为合格首轮。缺失输入身份的历史样本不补足资格。开发和留出分区不自动回流资格评分。
4. narrative Provider projection 移除 routing/grant 元数据，避免把候选供应商、成本与分区元数据带进评审上下文。原始审计资产仍保留。该修复本身不证明评审器可靠或完整盲评成立。
5. 现有 CLI 增加 `authority-provider-routing campaign`，只读原生历史策略和 reservation / Operation / ExternalEffect：查询所有采样授权、已用或保留额度、失败和待对账引用。没有把这份只读投影变成新的事实源。

6. 原语义评审支持明确授权的 `REFERENCE_EVALUATION` 采样，绑定独立 operator author 通过原生 `story_design.review.author` 登记的精确标签资产。标签不进入 Provider Context；输出保留逐标准一致/分歧、协议和谱系，明确是 operator proxy，不能生成领域 qualification 或推进候选。既有 POST 的 `dry_run=true` 返回可用于授权的 exact command/input hash；campaign query 返回各阶段 Operation 与产物引用。成功重放不重发。

7. 追加迁移 0139，保留已发布迁移和普通 Book Opening / qualification head 规则。参考采样使用原生 Kernel Operation，按授权区分同候选的 Flash / Pro arms；数据库禁止其写入领域资格。无效果或终态失败替代必须保留相同 candidate、model revision、actor、labels、campaign/sample 及前驱因果关系。成功结果和未知结果不得通过换 grant 重发。

8. Source Import 增加绑定已有原生冻结任务的采样准入和只读预检，覆盖 classification / deconstruction（保留当前章节读稿 observation / review / repair 路径）/ MKAOS extraction。模型臂继续经过原生调度器、Router、Provider admission 和 Kernel；回执缓存按授权隔离。采样产物与 ModelCallLog 为 INELIGIBLE / BENCHMARK_ONLY，三个 Authority 明确拒绝据此提交正式 Profile、Observation 或 KnowledgeCandidate。校准工作不进入正式导入、读稿进度与文件就绪统计；失败和成本仍保留在明细及 campaign 账本。终态无 ExternalEffect 的替代保留前驱，已有成功或未知 Effect 不可重发。Source 的终态 Provider 失败替代、独立评价与质量准入仍有缺口。

这里的 campaign 总额覆盖 **priced Planning / Source / reference bootstrap sampling**。正式生产、普通评审和 Codex entitlement 仍需要原有 project / Book / mixed-accounting 政策；本补丁没有声称已完成全阶段 campaign 授权闭合。

## 验证

当前 tested SHA 的 exact-SHA P0 为 `IN_PROGRESS`；定向检查与后端测试已通过，其余矩阵尚未形成最终结果。此段将在 runner 结算后更新。

Source 扩展已通过 20 项 Source/Router PostgreSQL 回归和 73 项相关单元测试；补充恢复后单独验证了三任务的双模型采样、无效果终态前驱替代、原正式导入状态保持不变和七次脚本调用累计结算。当前固定 SHA 的前置定向检查为 138 项。以上是工程 fixture，非真实 Provider 样本。

较早 Kernel reference 改动的定向回归为 91 项单元测试；80 项受影响 PostgreSQL 回归中 79 项通过，未知结果测试仅因投影字段误写为 status 而失败。修正为原生 state 后，该文件全部 5 项通过。其后修复的 19 个旧 gate 查询替身保留全部原断言，116 项相关单元测试通过；最终 P0 将再次验证完整矩阵。较早实现还通过 89 项单元和 59 项 PostgreSQL 测试，覆盖授权版本、跨 grant / run key 累计额度、未知结果占用、数据组与分区污染、重试删失、缺失身份和盲化投影。PostgreSQL 由本次临时容器提供，未使用用户业务数据库，定向测试容器和卷的最终清理见工程证据。

第一次 P0 在迁移兼容检查期间被主动中止：补充审查发现 sample ID 改名去重漏洞，需要新实现版本。中止记录保留为失败/中断证据，未冒充完整 PASS，未沿用它为后续实现背书。后续 `22cf0354c897fa383fa7def58cd8969e5cf02e88` 有单独的完整门禁运行；reference 实现改变后再次将全套门禁绑定到上面的 tested SHA，二者证据分开保留。

固定 SHA `5235672ce0f84f2fe4597d9234d8678b2959c1bc` 的 Kernel reference P0 在后端测试阶段失败：新增查询使 19 个旧 cursor 替身不匹配。数据库阶段为 NOT_RUN，清理 PASS。失败原始证据保留；仅更新替身和查询位置断言后，116 项相关单元测试通过，以新 tested SHA 再运行完整门禁。

固定 SHA `e9a9a75d25aacae1fa1f263410527b2f790537b6` 的重跑通过全量后端，但两项旧 Craft 迁移测试将 0138 硬编码为最新 head，导致兼容门禁失败。保留全部旧数据/约束断言，改为检查 0138 已安装且 head 等于当前 manifest 后，定向 PostgreSQL 两项通过。此前失败及清理 PASS 仍单独保留；最终再次全套验证。

工程测试均为 fixture / scripted engineering evidence，不计入真实校准样本或 Provider 消耗。

现有《借锋》冻结文件另经当前原生 `scripts.run_creation_synthesis` 做零调用配置校验，结果 `CONFIGURATION_VALIDATED_NO_PROVIDER_CALL`，见 [配置预检](native-config-preflight.json)。固定实现 SHA 与当前 tested SHA 一致；未连接业务数据库或启动 Provider。该配置目标为 120 章、试生产游标 40、读稿点 3/9/21/40、知识 DENY_ALL，因此不能直接宣称满足本包 12 章、3/6/9/12 和获准 Source 使用范围。旧冻结未修改。

## 任务与真实运行

[任务覆盖清单](task-coverage.json) 枚举 31 个原生实际或条件触发的 task_type，区分生成器、评审器与语义验证器，包含各自入口和源码摘要。它是静态调用图清单；条件任务的实际启用情况尚未通过冻结生产配置验证。

- Planning/Foundation 的 11 个单阶段 generator 有原生 challenger 入口。
- `narrative_semantic_evaluation` 已有原生 operator-proxy reference 采样与零调用 preflight；它不等于可信评审器已校准，已支持同一候选不同模型的配对采样，以及已证明无外部调用或终态失败的带前驱替代；成功/未知结果拒绝重发。
- Source 三个 task_type 已有原生冻结任务采样入口，包含同一 deconstruction task 下的生成与审阅角色；可信独立评价和质量准入仍未闭合。
- Chapter memo / draft / revision / Canon、World 双阶段及其他评审器的完整采样入口仍未闭合。
- Canon commit、Book Acceptance、accepted frontier、记忆投影属于确定性 Authority 边界，不能虚构为另一个模型任务。
- 所有列举任务本 campaign 的真实校准样本和独立留出样本均为 **0**；逐项 `NOT_PROVEN`。没有模型“不合格”的实测结论。

本包经 Novel Forge Provider runtime 发出的真实调用 **0**，tokens **0**，缓存命中 **0**，付费重试 **0**，其中 Codex 调用 **0**。执行开发任务的 Coding Agent 用量不在业务 Kernel 账本中，未取得可归因账单，记为 `UNKNOWN`；不能将研发或订阅使用说成免费。未查询账户实际账单。原稿 / 修订稿 / 接纳稿均 **0**；3/6/9/12 章连续读稿均 `NOT_RUN`；正式接纳、Canon diff、反馈消费对照和真实升级均 `NOT_RUN`。未创建空正文、短摘要或 fixture 来凑十二章交付。

## 授权与预算

[授权范围审计](authorization-audit.json) 已检查两份现有 operator 授权，它们绑定既有 project/book 和指定 Codex entitlement，累计 460 calls / 11,500,000 tokens 还包含历史使用，并明确禁止 Source 和付费 API。不能把这些授权挪作此次 DeepSeek、Source 或独立校准许可。当前进程未配置 DeepSeek secret；指定 Codex 二进制版本和摘要匹配，但其剩余 entitlement、远端可用性未证明。没有换账户、改计费模式或购买额度。

官方资料已重新核对并记录 URL、获取时间和内容摘要，见 [来源身份](official-source-identities.json)。Flash 使用 `deepseek-flash` / `DeepSeek-V4.1-Flash`，Pro high/max 使用 `deepseek-v4-pro` / `DeepSeek-V4-Pro-0813`；峰值缓存命中/未命中/输出单价每百万 token 分别为 Flash 0.006/0.3/1.2 USD、Pro 0.044/1.32/3.96 USD。[DeepSeek 官方价格](https://api-docs.deepseek.com/quick_start/pricing/)

Codex 订阅认证与 API 付费认证不能互换，entitlement 不折算为免费美元。[官方认证说明](https://learn.chatgpt.com/docs/auth)

[预算与实验草案](campaign-proposal.json) 提供分阶段的有限估算：DeepSeek 上限 2,800 calls / 86,000,000 tokens / 344 USD；Codex 32 calls / 6,976,000 tokens，货币成本 `UNKNOWN`；合计 2,832 calls / 92,976,000 tokens。生成、独立评价、修订、失败、升级和生产阶段均有额度。它按当前最高峰值 token 单价保守估算，不是账单，也不保证足够统计功效或 Provider 精确 token 硬上限。

**这仍是未冻结草案，不是完整待批准的可执行 manifest。** 精确独立数据/分组、可信 reference labels、Prompt/Context/Schema/Judge 资产版本、全族原生入口和全阶段授权绑定尚未准备齐。没有把“有一个预算数字”当作实验已经冻结，也没有发起现在就能执行整包的误导性审批。

## 分别给出的验收结论

| 结论 | 整包状态 | 证据边界 |
| --- | --- | --- |
| ENGINEERING_QUALIFIED | NOT_PROVEN | 有界修复的工程门禁见上；全族原生入口、完整 campaign 与恢复还未交付 |
| TASK_FAMILY_CALIBRATED | NOT_PROVEN（逐项） | 31 个 task 的样本计数和具体缺口见覆盖清单 |
| REAL_NOVEL_E2E_QUALIFIED | NOT_PROVEN | 0/12 章正式接纳 |
| CODEX_ESCALATION_REAL_EXECUTED | NOT_RUN | 没有真实升级调用 |
| QUALITY_NON_INFERIORITY_PROVEN | NOT_PROVEN | 没有独立留出；不得把无差异当作不劣 |
| COST_REDUCTION_PROVEN | NOT_PROVEN | 无合格产物成本分母；模型单价不能替代端到端收益 |
| COST_AWARE_QUALITY_CONSTRAINED_PROVIDER_ROUTER_PRODUCTION_READY | NOT_PROVEN | 原有独立校准与真实 E2E 阻塞仍在 |
| LONG_FORM_PRODUCTION_PROVEN | NOT_PROVEN | 未执行十二章，更没有长篇稳定性证据 |

## 阻塞归属与恢复边界

| 类别 | 未解决事项 | 现有 owner / 修复入口 |
| --- | --- | --- |
| 实现 | Chapter / World 多阶段等剩余 task-family 的安全采样与下游隔离；Source 终态 Provider 失败替代及独立评价 | Source Import、Chapter、Story Planning；复用各原生 admission / handler / commit gate |
| 实现与可信输入 | 可信标签/规则验证、成功远端结果缺少本地评审产物时的专用投影恢复；配对和带前驱无效果/失败替代已实现，operator-proxy reference 不自动构成 judge admission | Story Design `evaluation_runtime.py`；Chapter Quality `calibration_v2.py` |
| 实现 | 精确模型/Prompt/Judge 兼容分层、所有失败统计、冻结留出和后续反馈发布 | `PostgresRoutingRegistry.observations`、现有 quality / reader calibration / comparison |
| 授权/环境 | DeepSeek 预算与 secret、Source 作用域、Codex 新用途及余量 | 原生 operator / versioned policy / secret env |
| 统计 | 基线质量底线、不劣区间、所有成本和连续阅读效果 | 尚无真实数据，`INCONCLUSIVE`；不能归咎模型质量 |

已存在且经过本次回归的只读查询命令：

```sh
novel-forge authority-provider-routing campaign --project-id <authorized-project> --campaign-id real-provider-campaign-20260920
novel-forge authority-provider-routing metrics --project-id <authorized-project>
novel-forge authority-provider-routing replay --project-id <authorized-project> --decision-id <routing-decision-id>
```

Source 的原生操作入口为 `POST /product/source-imports/provider-samples?dry_run=true`（准备）及同一路径不带 dry_run（准入），请求含 project_id、source_operation_id、authorization_id、idempotency_key，必要时含 predecessor_operation_id；精确授权冻结和恢复边界见 [canonical 操作说明](../../../docs/runtime-operations.md)。这不是全任务 campaign runner。

这些命令只适用于原生政策/Operation 已存在的作用域。完整 campaign 尚不存在可直接执行的恢复命令，因此 manifest 的 `full_campaign_resume_command` 明确为 `null`。补齐上述原生入口、冻结数据与评价身份并获得匹配授权后，必须在新的固定实现版本上重新验证，再执行真实 campaign；不得用 adapter 直连、手写数据库或旧 qualification-only smoke 替代。
