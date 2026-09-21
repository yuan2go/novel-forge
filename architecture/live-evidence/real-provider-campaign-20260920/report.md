# Real Provider Calibration Campaign：实现与验收差距

**本工作包未完整交付。** 已提交原生采样、隔离、预算、证据兼容和恢复修复；真实校准、12 章生产、真实 Codex 升级及独立经济性比较尚未执行。仍有原生入口和评价准入的实现缺口，同时缺少作用域匹配的授权、可信评价输入及冻结实验数据。不能描述为“只差授权”，也不能把工程测试视为小说生产证明。

## 版本、文档与发布

| 身份 | 完整值 |
| --- | --- |
| 开始时实际 main / 工作包比较 baseline | `feba06582b6cadf2e80f5c573cf427114cf2a926` |
| baseline Git tree | `7fe1e48f3e7fe56666a5407f17c787b20c8c91c3` |
| baseline implementation identity | `sha256:e1dd43acca11bcecbb7e736e65332fa8824e305e85e6fa1ab503ed103a560537` |
| 已提交实现与回归确认 SHA | `76446099dee54b0248c9625a02e3d22b391c9086` |
| tested SHA | `45fa74ace314735112a3447e660c685172c6f79f` |
| tested Git tree | `14d1f4a7c7e8bcdb3dff27a08de466e30e054360` |
| implementation identity | `sha256:adf61a4234405b63f0edcfbd2ab942156bd98e0e544e3ad19b97fafd95778eed` |
| 最后核实的集成 main | `e41a2c22e4f24fdb89e6bb2db8a3e00039e7e332` |

测试分支为 `codex/real-provider-campaign-final-isolated-20260920`；证据分支为 `codex/real-provider-campaign-final-evidence-20260920`。baseline 至 tested 有 29 条祖先提交，包含另一工作流产生的合并与证据提交，不能全部算成本会话创建的提交。[Git 清单](git-state.json) 逐项记录文件范围与实现/测试、文档/证据、合并分类。最终证据提交更新本目录、原始 canonical P0 报告及 Reality 的对应投影，不改变上述实现身份；其完整 SHA 由 Git 与最终回复给出，避免在提交本身伪造自引用 SHA。

执行期间另一个汇总流程通过 [PR #93](https://github.com/yuan2go/novel-forge/pull/93)、[PR #94](https://github.com/yuan2go/novel-forge/pull/94)、[PR #95](https://github.com/yuan2go/novel-forge/pull/95) 提交并发布了本包工作树中的实现。PR #95 在 2026-09-20 15:52:56 UTC 合入上表 main；该 main 与 tested 的实现身份一致。此次测试随后移到独立克隆，避免共享 worktree 被并发提交导致 SHA 漂移。本会话没有 push、创建 PR 或 GitHub 合并，也没有覆盖原用户 checkout、既有作品冻结文件或已接纳正文。最终报告修订仍是本地证据提交。只读 GitHub 查询显示 Actions disabled，PR #95 的 statusCheckRollup 为空；当前 tested SHA 的远端 CI 为 NOT_RUN，远端分支治理不能由本地 P0 关闭。

文档清理先于业务修改，以 `2cd04a649aa9042f17470ae92d09263bd77de668` 独立提交：纠正真实 Provider 入口排他描述、旧迁移上限和价格脚注。[实现前缺口清单](preimplementation.json) 保留 owner、入口和修复位置。三个 proposal 经代码核对后仍有 G3/G4、Memory B–E 等未实现目标，因此保留并更新其生命周期和完整基线身份，没有为通过文档检查删除缺口。已发布迁移正文未改；本包只追加 0139。既有 Narrative Craft 和跨章 review / repair / rereview 路径保留。

## 已完成的原生修复

执行链仍为 owning Authority → `ProductionProviderRouter.select` → 冻结 `routing_decision` → Provider admission → Kernel reservation / ExternalEffect → receipt / settlement → Authority 产物或提交 → 原 benchmark 投影。未新建执行引擎、账本或 benchmark 数据库。

1. **授权、数据组和累计预算。** 版本化 `PROVIDER_ROUTING` 策略保留不可变 grant / campaign 身份；新 grant、run key、repair Operation 不重置原 Kernel 账本额度。同一输入版本集合不能换组名膨胀独立样本，也不能跨开发、校准、留出分区。未知外部结果继续占用并阻止盲重发。重新注册为新资产的同义或相同内容仍需要数据集审查；哈希检查不自动证明统计独立。每个 project 当前只绑定一个 campaign 是 `CURRENT_RUNTIME_FACT`，不是永久架构约束。
2. **Router v5 证据兼容。** 原观测查询在 LIMIT 之前按非空 producer contract hash 隔离 Prompt / Skill / Context / Schema / tool / projection 版本，并继续校验模型 revision 和服务端模型身份。原生任务缺少 contract hash 时不能借用历史分数。普通 Planning 生成 schema 的样本内绑定值与共享 schema 工厂身份分开，使不同合法输入可在相同生产契约下校准；每次调用仍保留精确 schema。World / evaluator 多阶段没有套用这一归一化。Judge、篇幅、风险层的完整兼容评价仍是单独缺口。
3. **首轮和失败证据。** 独立质量样本按 immutable group 首次尝试统计；重试仍进入费用和交付率，窗口截掉首轮的重试不能补成新首轮。缺失输入身份的历史调用不能补资格；开发、留出数据不自动更新资格。Source failure ModelCallLog 保留失败与成功的不同记录，不覆盖历史。
4. **评审器 reference 入口。** 现有语义评审通过明确的 `REFERENCE_EVALUATION` grant 采样，精确绑定原生 `story_design.review.author` 登记的独立 operator 标签、候选、协议与 hash。标签及路由/费用元数据不进入 Provider Context。双模型采样使用独立 Kernel Operation；不写 production qualification，也不推进候选。`dry_run=true` 返回精确 command / input hash。它是 **OPERATOR_PROXY** 对照能力，尚未证明可信 judge 准入，更不是人工真值。
5. **Reference 隔离与重放。** 迁移 0139 在数据库层隔离参考采样和正式 qualification head。成功重放复用原 Operation；替代只允许已证明无 Effect 或终态失败，并保留 actor、candidate、model、labels、campaign/sample 和前驱因果。未知或成功 Effect 禁止以新 grant 重发。终态成功但缺本地评审产物的专用投影恢复仍未补齐。
6. **Source 三个实际任务的采样。** 原生冻结 Source stage 经 `POST /product/source-imports/provider-samples` 准入，覆盖 `source.content.classify`、`source.deconstruction.observe`、`source.mkaos.extract`。仍走原调度器、Router、admission、Effect 和预算；receipt cache 按 grant 隔离。产物 INELIGIBLE / BENCHMARK_ONLY，三个 Authority 拒绝据此提交正式 Profile、Observation 或 KnowledgeCandidate。采样不增加正式导入进度；审计明细和费用仍保留。
7. **Source 失败与未知结果恢复。** 已证明未发送可以释放；已发送终态失败必须保留调用与测得或保守用量；未知、缺结果或缺费用证据保持占用。共享逻辑从 Chapter 移到已有 Kernel owner，保持 Chapter 语义。失败替代必须绑定最近同一 arm 的终态前驱；成功禁止替代，未知走原生查询对账。脚本回归在第九次执行出现未知后，以一次 query 取得原结果，execute 数没有增加，失败和成功两条证据均保留。
8. **查询与恢复入口。** `authority-provider-routing campaign` 从原生版本化政策、Operation、Effect 和 reservation 查询各阶段、已用/保留额度、失败及待对账引用；`metrics` 保留整个项目计量，`replay` 检查冻结决策。只读投影不成为新的事实源。

本包当前 campaign 总额覆盖 **priced Planning / Source / reference bootstrap sampling**。Bootstrap 仍明确限制 DeepSeek / PRICED；正式生产、普通评审与 Codex entitlement 尚未在同一 campaign 的全阶段混合计费契约中闭合。原有项目/Book 限额继续有效，本补丁未扩大任何授权。

## 工程验证与失败保留

完整 canonical `make pr-governance` / local P0 结果 **PASS**，包括强制数据库、迁移、恢复、查询计划与资源清理；各门禁、JUnit 数量和原始文件摘要见工程索引。

最终调用以固定 tested SHA、初始 baseline 做完整工作包差异检查。晚期 main 已被另一流程提前合入实现，若仅与该 main 比较，剩余差异只有 PostgreSQL 测试修正，仓库门禁无法自动取得所要求的非 PostgreSQL focused tests；因此最终以本包完整 baseline 运行，未删除门禁或新增无关测试来凑数。定向检查 **150 项通过**；全量 backend **2,840 项测试及 1,453 项 subtests 通过（4,293 条 JUnit 记录）**；PostgreSQL **781 项测试及 96 项 subtests 通过（877 条 JUnit 记录）**；迁移兼容 **92 项测试及 13 项 subtests 通过（105 条 JUnit 记录）**。上述三套全量结果均零失败、零跳过；迁移 head 为 `20260920_0139_narrative_reference_sampling`，与 manifest 一致。详情见 [工程索引](engineering-index.json)。

开发回归记录见 [定向工程证据](engineering-development.json)：producer contract 125 项单元及 60 项 PostgreSQL 通过；Source 恢复 68 项单元及 23 项 subtests 通过。其四文件 PostgreSQL 回归 43 项通过、1 项因测试查询中 `asset_id` 列歧义失败；修正连接条件后，完整 Source 采样/失败/未知恢复场景 1 项通过，最终 P0 再验证全量。以上均为脚本 fixture，不计为真实模型调用。

以下失败和先前成功均保留，旧 SHA 的成功不替代当前 SHA：首次执行因发现样本改名漏洞主动中止；`5235672ce0f84f2fe4597d9234d8678b2959c1bc` 因 19 个 cursor 替身未适配新增查询而失败；`e9a9a75d25aacae1fa1f263410527b2f790537b6` 因两项 Craft 升级测试硬编码旧 head 而失败。后者保留旧数据约束断言，只改为验证安装了 0138 且 head 等于当前 manifest。独立克隆首次前置检查缺少 `origin/main`；第二次因上述 focused 差异范围被拒绝，二者均未进入 P0 数据库阶段。每次失败有独立工程记录与清理状态。中间 SHA `8f502267a1df9d1aff52880079891ace5d18b9fd` 的重复 PostgreSQL 子进程在最终 SHA 全矩阵启动后被正常中断以释放资源，记为 FAIL / SUPERSEDED_INTERRUPTED、清理 PASS，不将未完成部分记作通过；见 [中断记录](superseded-gate-interruption.json)。

PostgreSQL 测试使用各 runner 拥有的临时数据库与资源，未使用用户业务数据库。两个开发 fixture 的容器/卷清理记录分别见 [原 fixture 清理](development-fixture-cleanup.json)、[Source fixture 清理](source-fixture-cleanup.json)；P0 清理由各运行报告绑定所有权。不能把环境失败算成 Provider 质量失败，也不能从测试通过推断真实业务接纳。

原始工程门禁文件另外按原字节打包，便于离开本机后核对 JUnit、过程日志和失败记录。该私有便携包不进入 Git；可公开的 [包清单与摘要](engineering-evidence-package.json) 绑定文件名、大小和 SHA256，仓库中保留 canonical P0 报告与逐文件 hash 索引。这些全部属于脚本工程证据，不是实际小说生产证据。

## 调用覆盖与真实结果

[覆盖矩阵](task-coverage.json) 列出 31 个实际或条件触发的 task_type、角色、owner、原生入口和当前源码 hash。27 个标为主链需要，4 个依 World preparation / Context coverage / Reader followup 配置触发。这是 **STATIC_NATIVE_CALL_GRAPH**，冻结生产配置尚未贯通，所以不能声称 31 个任务已全部运行。另记录一个条件性的 `retrieval` embedding Provider stage：原生文档投影和查询向量调用使用既有 embedding contract，不进入生成式 Router 比较，但若配置启用，调用与费用必须纳入端到端总额，不能遗漏。该激活及预算范围尚未冻结。

- 11 个 Planning / Foundation 单阶段生成器已有原生 challenger 入口。
- Narrative semantic evaluator 有上述 operator-proxy reference 入口；可信独立标注校验及评审器准入未证明。
- Source 三个任务已有原生采样与恢复；其可信独立评价和质量准入未闭合。
- Chapter memo / draft / revision / Canon extraction、World 双阶段及 Chapter Quality / Reader 等评审器的完整采样尚未补齐。Chapter 现有 operation completion contract 要求正式 eligible 产物并关联章节执行链；不能仅加 task_type 或绕过 scheduler 假装完成采样隔离。
- Canon commit、Book Acceptance、accepted frontier 和记忆提交是确定性 Authority 边界，不虚构成额外模型任务。

所有任务本 campaign 的真实校准和留出样本均为 **0**，逐项 `TASK_FAMILY_CALIBRATED=NOT_PROVEN`，没有模型“不合格”的实测结论。

| 指标 | 本 campaign 实际值 |
| --- | --- |
| Novel Forge Provider runtime 真实调用 / tokens | 0 / 0 |
| 缓存命中 tokens / 付费重试 / 真实 Codex 调用 | 0 / 0 / 0 |
| 原稿 / 修订稿 / 接纳稿 | 0 / 0 / 0 |
| 3 / 6 / 9 / 12 章连续读稿 | 全部 NOT_RUN |
| Book Acceptance、Canon diff、记忆/游标推进 | NOT_RUN |
| 真实 benchmark 反馈被下一次决策消费 | NOT_RUN |
| 合格产物成本 / 每万字接纳稿成本 | 无分母，不能计算 |
| 实际账单 / Coding Agent 可归因开发消耗 | UNKNOWN |

没有创建空正文、摘要或 fixture 凑十二章。Coding Agent 本身消耗不在 Novel Forge Kernel 账本中；订阅用量和未知费用没有记成免费美元。

## 授权、配置与预算差距

[授权审计](authorization-audit.json) 检查了两份现有 operator 授权，均绑定既有 project/book 与指定 Codex 账户，各自记录有限 lifetime 460 calls / 11,500,000 tokens 含历史使用，旧文件中的 Source 与付费 API 范围均受限。这两份额度不能相加或视为尚未使用。当前 WP 已明确授权实施 Source、reference evaluation、验证作品和 Codex 升级等工作，不需要重复询问是否要做；缺少的是与这些用途匹配且可执行的有限计费额度、剩余 entitlement 和原生政策绑定。旧文件不能自动变成新 campaign 的 DeepSeek 付费额度。所查进程与 operator 配置未提供 DeepSeek secret；指定 Codex 二进制及 hash 已核实，远端可用模型和剩余 entitlement 未确认。未切账户、改计费、购买或重置额度。

《借锋》已有冻结输入在 tested SHA 下经原生 `scripts.run_creation_synthesis` 零调用检查，结果 `CONFIGURATION_VALIDATED_NO_PROVIDER_CALL`，见 [配置预检](native-config-preflight.json)。未连接业务数据库或启动 Provider。现有作品目标 120 章、试生产 40 章、读稿点 3/9/21/40、知识 DENY_ALL，与本包 12 章、3/6/9/12、获准 Source 使用不同；原冻结未修改。先前不同实现身份的预检另存，未覆写成当前证据。

已重新核对官方模型、reasoning、价格与认证资料，记录 URL、时间和摘要：[来源身份](official-source-identities.json)。Flash 为 `deepseek-flash` / `DeepSeek-V4.1-Flash`；Pro high/max 为 `deepseek-v4-pro` / `DeepSeek-V4-Pro-0813`。峰值每百万 token 缓存命中/未命中/输出分别为 Flash 0.006/0.3/1.2 USD，Pro 0.044/1.32/3.96 USD；实际执行前仍需重新校验版本与价格。[DeepSeek 价格](https://api-docs.deepseek.com/quick_start/pricing/) [reasoning 参数](https://api-docs.deepseek.com/guides/thinking_mode) Codex entitlement 与 API 付费认证分别记录，不能互换。[Codex 认证](https://learn.chatgpt.com/docs/auth)

[实验与预算草案](campaign-proposal.json) 的有限拟议范围为 DeepSeek 2,800 calls / 86,000,000 tokens / 344 USD，Codex 32 calls / 6,976,000 tokens、USD UNKNOWN；合计 2,832 calls / 92,976,000 tokens。分配涵盖 reference、筛选、校准、留出、生产与失败储备。它是未获授权的停止上限，不是账单或 Provider 精确 token 硬保证。

**该草案不满足完整审批与执行条件。** [预算可行性](budget-feasibility.json) 按当前 Router v5 做纯算术：在全部独立样本满分、Schema 和接纳均完美且已有可信质量投影的假设下，27 个必需任务的双候选准入下限为 878 个产物；这不是实测样本，也不是不劣统计结论。若每任务按拟定首次 30 组配对留出，候选生成本身为 1,620 次，超过草案留出 720 次，差 900 次，尚未计独立评审、失败、修订、风险/篇幅层和生产验证。未据此自动加预算。

剩余冻结字段为：精确任务数据和组/分区；可信 reference labels / 规则与 judge 验证；剩余族的原生采样入口；逐任务 Prompt / Context / Schema / Judge 资产与版本；全阶段混合计费授权；固定 baseline 与 economic router 快照；作品原生资产及 source-rights / knowledge-use grants。不劣草案采用 30/60/120 预定查看点、全族/查看点多重比较控制、成对作品级区间、3/100 质量差与 5 个百分点接纳率差；这些仍需数据设计和功效计算后冻结。预算用尽或区间不充分应为 INCONCLUSIVE，不能看到 PASS 就停。

## 分项结论

| 结论 | 本工作包状态 | 适用边界 |
| --- | --- | --- |
| ENGINEERING_QUALIFIED | NOT_PROVEN | 有界补丁门禁状态为 PASS；全族入口与完整 campaign 尚未交付 |
| TASK_FAMILY_CALIBRATED | NOT_PROVEN，逐项 | 覆盖矩阵全部真实样本为 0 |
| REAL_NOVEL_E2E_QUALIFIED | NOT_PROVEN | 0/12 章正式接纳 |
| CODEX_ESCALATION_REAL_EXECUTED | NOT_RUN | 无真实升级调用 |
| QUALITY_NON_INFERIORITY_PROVEN | NOT_PROVEN | 无独立留出；统计比较尚未执行 |
| COST_REDUCTION_PROVEN | NOT_PROVEN | 无合格产物成本分母 |
| COST_AWARE_QUALITY_CONSTRAINED_PROVIDER_ROUTER_PRODUCTION_READY | NOT_PROVEN | 独立校准和真实 E2E 仍未成立 |
| LONG_FORM_PRODUCTION_PROVEN | NOT_PROVEN | 无连续十二章或长篇生产证据 |

## 具体恢复边界

| 分类 | 尚未解决 | 现有 owner / 入口 |
| --- | --- | --- |
| 实现 | Chapter / World / Quality / Reader 采样、非生产产物隔离与 evaluator 冷启动 | Chapter Authority `runtime.py` / `definitions.py` / `scheduler.py`；Story Planning `world_preparation.py`；Chapter Quality / Book Followup |
| 实现与可信输入 | 可信独立标签或可验证规则；成功远端结果缺本地产物的 reference 投影恢复；Source 独立评价准入 | Story Design `evaluation_runtime.py`；Chapter Quality `calibration_v2.py`；Source / MKAOS Authorities |
| 实现 | 全阶段 campaign 额度包含正式生产与 Codex entitlement；冻结 holdout 及评估后反馈发布 | 原 Kernel `routing_bootstrap.py` / budget policy 与 Router registry；不另建账本 |
| 授权 / 环境 | DeepSeek 有限付费额度与 secret、Codex 可复用的剩余额度；当前 WP 已授权业务用途，仍需准确绑定原生政策及作品配置 | operator 授权与原版本化政策 / secret env |
| 数据 / 统计 | 冻结独立任务、风险/篇幅/Judge 层、baseline floor、区间与端到端经济结果 | 尚无真实数据，INCONCLUSIVE；不是已测得模型质量不足 |

已实现的查询可直接针对已有 native project / Operation 使用：

```sh
novel-forge authority-provider-routing campaign --project-id <authorized-project> --campaign-id real-provider-campaign-20260920
novel-forge authority-provider-routing metrics --project-id <authorized-project>
novel-forge authority-provider-routing replay --project-id <authorized-project> --decision-id <routing-decision-id>
```

Source 的操作为 `POST /product/source-imports/provider-samples?dry_run=true` 准备，再由同一路径不带 dry_run 准入；输入 project_id、原生 source_operation_id、authorization_id、idempotency_key，失败替代另带 predecessor_operation_id。Narrative reference 使用现有 `POST /product/production/book-authority/books/{book_id}/planning-evaluations` 及 `dry_run=true`。精确字段、授权和恢复边界见 [canonical 操作说明](../../../docs/runtime-operations.md)。

完整 campaign 的输入、原生入口和授权尚未闭合，因此 `full_campaign_resume_command=null`。没有捏造一个现在就能完成全包的命令，也没有把这份阶段交付包装成完整待批准 manifest。真实 campaign 必须在补齐上述缺口后，基于新的已提交固定实现/实验版本执行；旧 fixture、旧 Prompt/Judge 或未兼容样本不自动继承资格。

## 可迁移的代码与工程证据

代码及公开报告保存在上述证据分支，仓库相对入口为 `architecture/live-evidence/real-provider-campaign-20260920/index.json`。另附 `novel-forge-real-provider-campaign-20260920.bundle`，以 baseline `feba06582b6cadf2e80f5c573cf427114cf2a926` 为 Git prerequisite；原始工程记录包文件名和摘要见工程包清单。取回分支时可以先核验 bundle，再 fetch 到 `FETCH_HEAD`，不覆盖当前 checkout：

```sh
git bundle verify ./novel-forge-real-provider-campaign-20260920.bundle
git fetch ./novel-forge-real-provider-campaign-20260920.bundle codex/real-provider-campaign-final-evidence-20260920
git show FETCH_HEAD:architecture/live-evidence/real-provider-campaign-20260920/report.md
```

这些命令恢复本次代码与证据交付，不会执行 Provider 调用，也不是完整 campaign 的运行命令。
