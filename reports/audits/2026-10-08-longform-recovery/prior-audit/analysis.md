# 作者优先真实调用对账专项核查

结论：现有原始证据不足以安全确认原调用的远端结果或用量。当前真实短行程仍为 BLOCKED_BEFORE_PROSE，保存正文 0 章。代码存在精确的历史对账/Planning query/用量投影/Formation 恢复衔接缺口；这些缺口可修复，但不能代替缺失的远端证明。原作品库认证问题独立存在。

## 身份和核查范围

最终远端 main 为 fae50391c8e5e4b323aa303a922b8332e4e14666。PR #140 于 2026-10-08T00:16:01Z 合并；PR head ebfe7315390c0d075271ce00c04b42c12f35becd 与合并后的 main 的 Git tree 均为 f0a759e006f7dfc5ba321a14674ffd55a5c2814e，内容差异为零。本轮 55 项定向单元检查运行于这一相同 tree 的 PR snapshot。

开始核查时远端 main 尚为 7beea32acf7479e220f289e33ab71246e252009e，PR 仍 OPEN；本轮再次查远端发现其合并，已以合并后的 main 作为最终结论基线。没有执行 merge/push/业务修改。

输入为 architecture/live-evidence/wp-novel-production-closure-01/author-first-20261008/execution-evidence.json。真实调用 runtime SHA 为 b78b7431a70042d571117d0ec5773ee6c688c76c，不是最终代码资格证明。工作区原有脏文件保留；代码来自 /tmp/nf-provider-recovery-20261008/pr140 冻结快照。所有数据库调查设置 default_transaction_read_only=on。

## 原始事实

- 独立调用库仍可连接：database=nf_author_first_live，OID=224588，port=55489，cluster system_identifier=7693971203661179544，data_directory=/tmp/nf-author-first-pg.jxLglu/data。绑定与交付证据一致。
- Formation 保持 WORLD_BIBLE / FAILED / version 6；原 child Operation 为 FAILED_RETRYABLE / version 3。
- Effect b250d895-6122-4c5f-b723-4aaac40c0dae、Operation eea272cd-8a79-43d4-9821-9daff573c023、dispatch 38e101b8-8747-438d-8fe4-b0d3fc0509f5 / generation 1 均为原始身份；没有 manual resolution 或 reconciliation evidence。
- Effect request hash 与按保存 payload 重算的 hash 一致：sha256:108ea18235527a3e2f88d415953a1b39a255fbac20f4bbae1f808cb997f34ada。
- 本地 process-receipt.json 与 Authority AssetVersion e2ee46e9-4486-44e9-a3aa-639ed5de589e 的 payload 完全一致；payload hash 一致；三版 execution recovery session 的 record hash 一致。最新缓存仍是 RETRYABLE_FAILURE。
- 进程从 2026-10-07T18:40:17.603378Z 到 18:47:12.468689Z，returncode=1、status=FAILED、result_integrity=MISSING。没有 last-message.json；raw_output_ref、normalized_output_ref、usage_receipt_ref、cost_receipt_ref、Provider receipt/request ID 均无。
- stdout 1137 bytes，sha256=35fbfab2848ba6d6b9309e68e0e56cb666cd250ddd9f9b515230344e482102ec；只有 thread.started、turn.started、配置提示、stream disconnected error 与 turn.failed，无 agent_message、turn.completed 或 usage。
- 有诊断 thread_id=01a117aa-94f4-7ac1-973f-e9bc73db2f43。它没有保存在本地 threads 表；相应线程没有 logs_2.sqlite 记录；本地日期范围的会话搜索没有找到该调用 rollout。调用命令包含 --ephemeral，因此不能假设存在可离线读回的 Codex session。thread ID 不等于 provider request ID。
- 五次成功实测 token 总和 116645；第六次账本 105856 是 RESERVATION_CEILING，measurement_available=false、entitlement_usage_reconciled=false，不能纳入实测。会员金额 UNKNOWN 不是零。
- 当前 checkout 配置 localhost:5432/novel_forge 仍认证失败；docker info 仍无法连接 daemon。这不证明原作品业务数据不存在，也不证明其身份就是独立运行库。没有改密码、启动 Docker 或改接其他库。

## 代码和执行路径

FormationGenerationPort -> StoryPlanningGenerationApplication -> existing Planning worker/run_or_recover -> _PlanningPepPort -> dispatch_external_effect -> _PlanningGatewayEffectAdapter.execute -> ProductionExecutionGateway.submit -> CodexCliExecutionBackend -> durable process/execution evidence -> Kernel dispatch outcome + budget settlement -> Formation failure。

Kernel 在业务事务外调用 Provider，原 intent、payload/hash、dispatch、process receipt、Attempt/fence 已保留。恢复应读取这些原记录并追加 evidence，由原 Authority 消费结果，不能新建业务工作绕过。

| 核查项 | 最终 main 的事实 | 判断 |
| --- | --- | --- |
| Codex 非零退出分类 | backends.py:1466 将 FAILED 映射 UNKNOWN；历史已保存失败不改写 | 原分类缺陷已修复，勿重复实现 |
| 历史未知调用识别 | budget_runtime.py:4208 识别 RETRYABLE_FAILURE + PROCESS_EXIT_FAILURE 且缺用量 | 在真实库读到 1 条；派发检查报 EFFECT_CLI_OUTCOME_RECONCILIATION_REQUIRED |
| 自动对账 | external_effect_runtime.py:1293 只接受 DISPATCHING/DISPATCHED/UNKNOWN/RECONCILIATION_REQUIRED | 历史 FAILED_RETRYABLE 不能进入 |
| 人工解析 API | content_authority.py:233 -> manual_effect_resolution.py:42，后者只接受 UNKNOWN/RECONCILIATION_REQUIRED | 也不能解析本例；不能先手改 status 再调用 |
| Planning query | execution.py:3309 直接 execute；execute 调 gateway.submit/reconcile | 不是独立远端查询；记录存在时读缓存，缺失时有启动调用风险 |
| CLI reconcile | backends.py:1706 有 record.result 就直接返回；supervisor 只恢复本地进程证据 | 无法通过重跑 reconcile 补出远端终态或用量 |
| 查询结果枚举 | Kernel 接受 success/not_found/ambiguous/failed_final/cancelled；Planning adapter 沿执行枚举返回 retryable_failure/unknown | 恢复协议未闭合；不要把进程失败映射为远端 not_found |
| 历史用量对账 | external_effect_runtime.py:_resolve_reconciled_budget 只选 RESERVED/HELD_UNKNOWN | 忽略本例 SETTLED 保守估计，需追加实测对账证据/投影 |
| Formation 恢复检查 | creation_runtime.py:_formation_resume_blocker 在原库返回空字符串，同库 unresolved_cli_outcomes=1 | 底层阻止发送，但恢复前状态检查未复用原未知证据 |

上表的状态属于 CURRENT_RUNTIME_FACT。保留原身份、未知结果先对账、历史证据不可改写由实现/gates 与原调用记录支持，作为本专项 CURRENT_PROVEN_INVARIANT。作者优先模式及恢复次数上限为 CONFIGURABLE_POLICY/版本化合同策略，旧分类与 frozen runtime 是 HISTORICAL_COMPATIBILITY。当前会员通道能否提供丢失请求的远端逐调用结果及用量属于 UNRESOLVED_DESIGN_CONSTRAINT；本轮没有找到可执行的远端读取入口，不能猜测存在。

## 恢复条件和技术路径

1. 保留独立运行库、原 object store、runtime root、原 stdout/schema/receipt 和全部五次成功结果。原作品库单独核实 endpoint、database/OID/cluster、migration、Project/Book/Formation/ledger。不能把独立验证库接成原作品库。
2. 在相同账号、原时间窗和诊断 thread ID 下，只读取得可信远端终态及逐调用消费：完整原结果 + 终态用量；或可信失败/未执行/取消证明 + 实际用量/明确无消费证明。不要运行 codex exec resume 或 prompt 询问原模型。不要把不存在的本地会话当作 remote not_found，也不要用账号总用量差推算本次消费。若已有可确认不会发起推理的官方查询入口，先证明其协议/身份绑定再查询；否则由服务方证据补齐，不能自行编造接口。
3. 给原 Effect、dispatch generation、Execution、request hash、frozen Schema/Pack/Router、账号、trace、输出 hash 与用量绑定追加恢复证据。当前两个解析入口都不能处理此历史状态，必须先补最小代码路径，不可用 SQL 改历史状态去绕过。会员金额允许继续 UNKNOWN。
4. 若找回成功输出，验证原 schema/identity，host-only 接纳结果，不重调 WORLD_BIBLE，不重做五次成功。若明确可重试且消费已对账，让原 Kernel 策略选择允许的新 generation/因果 successor；这些属于新的执行，非只读查询。未决期间仍禁止发送。
5. 再沿原 Formation 的原生 version-CAS resume/recover 和 frozen_input_digest 恢复，继续必要 Planning -> Opening -> Draft 保存。FAILED Formation 本身有原生 resume，不必新建 Formation；底层 terminal Operation 如需 successor 则保持因果证据和历史。当前版本数字只供核查，执行恢复前须重新读取。

只有完成第 2-4 步后，才可运行以下原生控制命令。恢复键是控制命令幂等键，不是替换原 Provider 请求键。凭据通过私有 env 加载，代码须使用已验证的修复版本，原冻结调用合同不改写。

```bash
novel-forge authority-runtime-inspect --project-id author-first-live-20261008T023028-final
novel-forge authority-creation recover \
  --project-id author-first-live-20261008T023028-final \
  --formation-run-id story-formation:52180f1fa7e46240b0073b4a2eedbd8babd1ddde33ef1487f8071ad2ae03473b \
  --reason "$VERIFIED_RECOVERY_REASON" --idempotency-key "$RECOVERY_CONTROL_KEY"
novel-forge authority-creation continue \
  --project-id author-first-live-20261008T023028-final \
  --formation-run-id story-formation:52180f1fa7e46240b0073b4a2eedbd8babd1ddde33ef1487f8071ad2ae03473b \
  --foreground
```

本轮没有执行上述控制/Provider 命令。证据未找回时，代码修复只能完成恢复入口，真实正文仍 BLOCKED；不提高预算、不改作者方向、不增加审读审批。

## 验证边界

- PASS：真实库只读身份核实；Effect payload hash、原 process receipt 和 execution session record hashes 一致；原未知 diagnosis/send guard 生效；Formation 恢复前检查缺口定向读回。
- 旧 main 的同库未决查询返回 0、lineage guard ALLOWED；合并后的同 tree 查询返回 1、guard 拒绝。此结果只证明该检查的差异，不声称完整派发链能在旧 main 绕过所有约束。
- reconcile 状态检查依据真实读取的 status 做无 I/O 的函数探针，返回 EFFECT_STATUS_CONFLICT、adapter query 次数 0。直接在只读事务执行原函数会因内部 SELECT FOR UPDATE 被 PostgreSQL 拒绝，未运行其写路径。
- PASS：tests/unit/test_local_cli_remote_outcome_guards.py、test_gateway_effect_unknown_outcome.py、test_creation_recovery_control.py，共 55 passed in 0.71s。均为单元/模拟证据。
- NOT_RUN：新增修复、写数据库对账、Provider 请求/重发、原作品恢复、完整适用实现矩阵、全仓回归、真实正文跨章/改稿/导出、文学资格。
- 整体证据上限保持 EXECUTABLE；本专项不升级为 QUALIFIED 或 PRODUCTION_PROVEN。

## 来源

- https://github.com/yuan2go/novel-forge/pull/140
- https://github.com/yuan2go/novel-forge/blob/fae50391c8e5e4b323aa303a922b8332e4e14666/architecture/live-evidence/wp-novel-production-closure-01/author-first-20261008/execution-evidence.json
- https://github.com/yuan2go/novel-forge/blob/fae50391c8e5e4b323aa303a922b8332e4e14666/src/novel_forge/modules/command_kernel/external_effect_runtime.py#L1293
- https://github.com/yuan2go/novel-forge/blob/fae50391c8e5e4b323aa303a922b8332e4e14666/src/novel_forge/modules/command_kernel/manual_effect_resolution.py#L42
- https://github.com/yuan2go/novel-forge/blob/fae50391c8e5e4b323aa303a922b8332e4e14666/src/novel_forge/modules/story_planning_runtime/execution.py#L3309
- https://github.com/yuan2go/novel-forge/blob/fae50391c8e5e4b323aa303a922b8332e4e14666/src/novel_forge/modules/production_execution/backends.py#L1706
- https://github.com/yuan2go/novel-forge/blob/fae50391c8e5e4b323aa303a922b8332e4e14666/src/novel_forge/modules/book_authority/creation_runtime.py#L367
- https://developers.openai.com/codex/cli/reference/ ：--ephemeral 不持久化 rollout，exec resume 是继续会话。
- https://developers.openai.com/codex/noninteractive/ ：JSONL 的 turn.completed 用量及 resume 后续任务语义。
