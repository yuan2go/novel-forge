# Codex 专项修复提示

在 yuan2go/novel-forge 最新 main 上，只修复原作者优先真实调用的 UNKNOWN 对账和恢复衔接。开始时重新冻结远端 main；本轮最后核实为 fae50391c8e5e4b323aa303a922b8332e4e14666，已合并 PR #140，tree=f0a759e006f7dfc5ba321a14674ffd55a5c2814e，与 PR head ebfe7315390c0d075271ce00c04b42c12f35becd 完全相同。作者优先交稿架构已实现，不重新设计，不增加作者审批，不扩大全工程审计。遵守 AGENTS.md；保留原工作区的脏文件，在隔离 checkout 开发。

## 冻结事件

- 输入证据：architecture/live-evidence/wp-novel-production-closure-01/author-first-20261008/execution-evidence.json。
- 真调用代码 SHA：b78b7431a70042d571117d0ec5773ee6c688c76c；不是最终实现 SHA。
- Project：author-first-live-20261008T023028-final；Book：author-first-live-20261008T023028-final-book。
- Formation：story-formation:52180f1fa7e46240b0073b4a2eedbd8babd1ddde33ef1487f8071ad2ae03473b；WORLD_BIBLE、FAILED、version=6。
- Operation：eea272cd-8a79-43d4-9821-9daff573c023；FAILED_RETRYABLE、version=3。
- Effect：b250d895-6122-4c5f-b723-4aaac40c0dae；FAILED_RETRYABLE。
- 原 dispatch：38e101b8-8747-438d-8fe4-b0d3fc0509f5；generation=1；FAILED_RETRYABLE。
- stable key：eea272cd-8a79-43d4-9821-9daff573c023:world.design.generate:planning-pep-v2。
- request hash：sha256:108ea18235527a3e2f88d415953a1b39a255fbac20f4bbae1f808cb997f34ada。
- Execution：planning-execution:b250d895-6122-4c5f-b723-4aaac40c0dae:0db02dd3-5321-4962-aba9-6ea15ab6e67b；original Attempt=0db02dd3-5321-4962-aba9-6ea15ab6e67b、fence=1。
- process receipt：authority-asset-version:e2ee46e9-4486-44e9-a3aa-639ed5de589e；content hash=sha256:a944de0d1180672d895c9cc00b356fb1c662b15716f4aef3c3bd4e264b7f2581。
- 原 stdout thread_id：01a117aa-94f4-7ac1-973f-e9bc73db2f43；仅用于关联调查，不等于 Provider request ID，不具备远端幂等保证。
- Runtime root：/Users/yuan/.codex/author-first-live/20261008T023028-final。env.json 含私密配置，只在内存读取，禁止输出或提交。
- 独立数据库：nf_author_first_live、port=55489、OID=224588、system_identifier=7693971203661179544、data_directory=/tmp/nf-author-first-pg.jxLglu/data、migration head=20261008_0181_author_manuscript_delivery。它不是已绑定的原作品库。
- 历史 reservation=866da76a-b44c-4cdb-bddf-d6c262679c7f，SETTLED，105856 token，measurement_available=false、usage_settlement_basis=RESERVATION_CEILING、entitlement_usage_reconciled=false。105856 是估计，禁止改为实测。会员金额继续 UNKNOWN。

## 已证实缺口与最小改动

1. main 已将未分类 Codex FAILED 退出映射为 UNKNOWN，并识别历史 RETRYABLE_FAILURE + PROCESS_EXIT_FAILURE。复用这些修复，不再实现一遍。主入口为 command_kernel/external_effect_runtime.py:reconcile_external_effect；但它只接受 DISPATCHING/DISPATCHED/UNKNOWN/RECONCILIATION_REQUIRED。manual_effect_resolution.py:resolve_external_effect_manually 只接受 UNKNOWN/RECONCILIATION_REQUIRED。两者都拒绝本次历史 FAILED_RETRYABLE。
   在既有 Kernel owner 内补充精确的历史 CLI 对账路径：必须以本次冻结身份、已启动进程、缺失终态用量、原 generation 和可信证据为条件，不泛化放开所有 FAILED_RETRYABLE，不把历史状态直接改成 UNKNOWN。复用既有 reconciliation evidence、AssetVersion、Operation/UoW 和审计事件，追加版本化恢复记录与幂等证据读取分支；任何新 schema 只追加迁移，不修改已发布迁移。旧失败 dispatch/Attempt、冻结 request 和已结算账本保持原样。

2. story_planning_runtime/execution.py:_PlanningGatewayEffectAdapter.query 当前直接调用 execute，后者调用 gateway.submit。缓存存在时只是返回旧 handle/result；缓存缺失时 submit 有启动新进程的风险；返回 retryable_failure/unknown 也不是 reconcile_external_effect 所接受的查询 outcome。
   使 query 只读取原 persisted ExecutionRequest/Handle，并使用已有 gateway.recover_existing_execution 及 Kernel recovery Attempt 的有效 lease/fence；缺少原执行记录时保持 ambiguous，绝不 submit、resume_planned_execution 或创建新的调用身份。对本次缺终态/用量的历史缓存返回 ambiguous；不把本地失败、文件缺失或 CLI turn.failed 解释为远端 not_found。仅以可信远端终态证据规范化 success/not_found/failed_final/cancelled。不要把已保存 UNKNOWN/non-success result 当成远端查询结果。

3. _resolve_reconciled_budget 只处理 RESERVED/HELD_UNKNOWN，忽略本次已经 SETTLED 的保守估计。补齐原 reservation 的版本化用量对账证据和当前读投影：历史估计仍可读，追加实测与来源，不重复累计、不把旧 actual_tokens 覆盖成实测、不凭空释放估计。未知或冲突用量保持未决；ACCOUNT_ENTITLEMENT 金额 UNKNOWN 本身不阻止已证明的 token 对账。不要以一个不完整 manual resolution 行就消除未决状态。

4. book_authority/creation_runtime.py:_formation_resume_blocker 在本库返回空字符串，但 unresolved_cli_outcomes 返回 1。Formation resume/CLI recover 前复用同一 unresolved-cli predicate，先报告 RECONCILIATION_REQUIRED，再允许状态推进；不是新的作者审批。对账成功后沿原 Formation identity/frozen_input_digest/version 的原生 resume，复用前五次成功结果，再到必要 Planning、Opening、Draft 保存。形成新 recovery Operation/Attempt 或确有条件的新 dispatch generation 时，要保留因果链；不新建作品、Formation、作者方向或请求来绕过未决原调用。

只在可信结果已找回时追加原结果完成/接纳证据并通过原 Schema/Pack/Router/domain validation，保证 host-only 恢复不调用模型。若可信远端失败/未执行且用量已明确，才让已有恢复策略决定同 Effect 新 generation 或有明确因果的 successor；这两种均是新的可能消耗额度的执行，不得冒充查询。证据不足时保持 RECONCILIATION_REQUIRED，并明确列出唯一缺失的远端证据；代码修复不能创造遗失输出或未知用量。

## 定向验收

以隔离 PostgreSQL fixture 验证：

- 历史 FAILED_RETRYABLE + PROCESS_EXIT_FAILURE 的真实形状；普通 pre-start retryable 不进入此恢复分支。
- query、导入证据、恢复重放的 Provider execute/submit 次数严格为 0；原 execution 缺失、expired old fence、证据身份或 hash 冲突均拒绝。
- 同恢复幂等键的重复输入只返回原记录；改变证据报 conflict；恢复进程中断后使用原证据继续，不重复调用。
- 成功结果和 token 用量证据完整后，原五次成功不重做、WORLD_BIBLE 原结果只消费一次；保留旧失败 dispatch、Attempt 和 SETTLED 估计。
- 可信未执行/失败与未知消费明确区分；无远端证明的 turn.failed 不允许新 generation。
- 未决调用阻止 Formation 恢复前的状态推进；可选独立审读的既有不相干范围例外保持不变。
- 已知旧 SETTLED 估计的实测对账不会双计数；会员金额仍 UNKNOWN；DeepSeek 已有付费上限保持。
- 正文一旦保存立即沿既有作者优先交稿机制可读；仅在以后真实执行获授权且证据条件满足时验证原短行程的保存、续写、修改和精确版本导出。

开发先跑最小失败回归，完成时按 docs/runtime-operations.md 执行完整适用矩阵（限定 Kernel receipt/lease/fence、Planning recovery、Formation、budget、必要迁移/装配），不得扩为全仓或长期文学资格。真实 Provider 验证默认 NOT_RUN；不得为测试重复消耗额度。

交付修复 diff、定向检查结果和恢复条件，分别标记 CODE_EXISTS/WIRED/EXECUTABLE/QUALIFIED/PRODUCTION_PROVEN。不要宣称 fixture 或六章受控测试已经交付真实正文。不得替换请求身份、更新历史账本、提高额度、新建审批门或增加平行 Writer/Runtime/Authority。
