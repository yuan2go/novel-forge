# Novel Forge PR 133 集成执行工作包

从最新 main 建立集成分支，按恢复语义移植 creative-validation-resources 的必要增量。保留 native production closure 的 Authority、取消、调度、容量、已知结果恢复与 Context Router 约束。禁止旧分支整包覆盖、直接合并原 PR 树或按文件选择 ours/theirs。

## 固定输入和交付边界

- 仓库：yuan2go/novel-forge。
- main：`f9e1ee5e115fd47b8bb9d97a35aa2813b7e04609`；PR 132 已合入此提交。
- PR 133：`ad1c229d4b17db45fa14c73dcc6569e8655c82c9`，OPEN、draft、CONFLICTING。
- 共同祖先：`e2064ede68920f680204c40486bf69f1901fb770`；PR 发布记录的旧基线另为 `2cb74ed135c7a48e1ca72b4d456113dfd3f78dc3`。两者不得混用。
- 2026 年 10 月 7 日分页 API 核实：PR 133 保留 32 个提交、132 个 changed paths；PR 132 为 148 个 paths；重叠 24 个。只读 `git merge-tree --write-tree main PR133` 产生 17 个文本冲突。这些统计不代表语义冲突的全部范围。
- 本轮是核查与执行设计：生产源码、数据库、远端分支均未修改；回归、迁移执行、构建和真实 Provider 均为 `NOT_RUN`。
- 静态调用链可报告 `CODE_EXISTS`、`WIRED`；本轮没有新增 `EXECUTABLE`、`QUALIFIED` 或 `PRODUCTION_PROVEN` 证据。
- 不调用 Codex/DeepSeek 等真实 Provider，不启动生产服务，不迁移真实数据库，不复用运行中 Book 或历史验证作为当前验证。后续执行只使用自有 disposable PostgreSQL 和外部 I/O substitutes。

## 逐项恢复语义裁决

下列路径均相对 `src/novel_forge/`；判断绑定上述两个 SHA。

| 语义 | main 证据与覆盖程度 | 集成裁决 |
| --- | --- | --- |
| Planning 无 Candidate 的原始结果修复 | `modules/story_planning_runtime/result_recovery.py:129` 与 `application.py:1896` 已验证完整冻结任务、结果来源、成功 receipt、结算，并追加有界 repair | 已覆盖主体。退役分支平行实现；只补其原 Context/hash 和 author projection 校验、独立的合法结果准入入口 |
| FAILED_FINAL 与 DEAD_LETTER 的已知结果恢复 | main `result_recovery.py:150` 阻断未决 Effect；Kernel `external_effect_runtime.py:145` 接受两种终态；main 0159 SQL 绑定原结果和因果链 | 保留 main。分支仍只接受 FAILED_FINAL 的条件不能覆盖回来；CANCELLED 与 UNKNOWN 不能泛化为已知结果修复 |
| Planning 容量 successor | main `runtime_continuation.py:265`、`:338`、`:419` 已覆盖零 intent/reservation/冻结 Context、会员连续创作授权、两次上限、输出与 framing allowance；main 0158 保留精确 capacity 与已准入 repair-origin cause | 已覆盖连续创作容量主路径。保留 main；移植分支对历史 raw repair、route/input-order preflight 的额外来源校验，作为互斥原因分支；不同来源前提不得统一放宽 |
| raw repair 跨 runtime continuation 的持久 lineage | main execution lineage 已处理 continuation 的 repair delta 为 0；但 main 没有分支新增的 generation.runtime_continuation_id 列及索引 | 部分覆盖，必须移植列、索引、回填和 generation guard；不得重置 repair counter、raw source 或候选来源 |
| native bounded repair routing | main `execution.py:321` 原生 receipt → `routing_runtime.py:722/1242` → `cost_routing.py:823` 的 governed_repair，绑定新旧 input hash、完整历史和发送时再验；分支另有 native_planning_repair 与模板放行 | 主体已覆盖。新选择保留 main 单一判定链；移植 v4-v6 的每阶段 ordinal 与完整 role-to-artifact 校验。分支第二套独立放行仅可保留为有版本的冻结证据兼容读取，不能再独立授予权限 |
| input-order / blocked-route 零发送 preflight 恢复 | main 没有 `preflight_continuation.py` 的此类恢复来源；main 容量路径并非它们的等价替代 | 必须移植。精确失败/blocked decision、无 Effect/reservation/live attempt、原候选、role map、counter、route/account 和注册证据全部匹配 |
| Foundation 合法保留结果补准入 | main 的 result repair 针对非法 raw，合法 raw 会得到 REPAIR_NOT_REQUIRED；没有 result_admission 表或命令 | 必须移植 `result_admission.py:24`。LOCAL_OPERATOR、显式 reason、原结果/Context/Pack/Fence/输入、creative policy 和 settled success；创建 CANDIDATE/INELIGIBLE，继续普通 Story Design 审批，不授权重发 |
| 合法 completed candidate 跨 release replay | main 已有 `_terminal_generation_replay`，但未覆盖分支的未选中 candidate 与新 result-admission 路径 | 增量移植这些状态；保持不可变已准入 payload，区分历史读取与未执行 successor 的新 release/Pack admission |
| World typed transition、schema/causal rejection 修复 | main `production_schema.py:29`、`world_preparation.py:554/767` 已交付 typed 合同并复现因果拒绝，验证 Director receipt，复用所选 action | 主体已覆盖，退役平行修复。补分支精确 Arc/obligation refs、已结算 checkpoint 的本地恢复；保留 main WORLD_GENERATION_CAUSAL_REJECTED 与 exact frozen action。不可把 malformed output 或因果拒绝归为可自动忽略的 World |
| 可选 World future preparation 与 DEFER | main 没有 `world_optional.py`、显式 REQUIRED/OPTIONAL/DISABLED 和 settled deferral command | 必须移植。只放行有原生 creative policy 的 OPTIONAL/DISABLED；REQUIRED、strict、已接受 preparation commitments、独立 actor experiments 保持阻断。DEFER/NOT_RUN 不生成已接受事实 |
| literal-null 导致完整 Codex 输出被本地误拒 | main 没有 `gateway_result_recovery.py` 与 rejected completion reader | 必须移植。只复核原冻结 schema 与完整 process/result hash；保留 FAILED_FINAL Effect/Attempt 与费用，附加 recovery candidate；完整性不足或 UNKNOWN 一律阻断 |
| Planning 每 Provider stage repair allowance | main 是全 lineage 有界修复及明确 owner wait；分支 stage_repairs 增加 World 与 ChapterPlan 的不同 allowance | 必须移植显式 v4-v6 授权的 stage ordinal；monotonic counter 不回零，stage 上限两次、总结构上限四次；v1-v3/strict 保留旧语义；不能把 owner wait 改成无限重试 |
| worker failure 分类 | main 将 model capacity metadata UNKNOWN 定为 MANUAL_INTERVENTION，将真实未决外部状态归为 UNKNOWN，将 repair bound 归为 owner wait；分支将 OUTPUT_CAPACITY_UNKNOWN 归为 FINAL_FAILURE | 退役分支的 metadata UNKNOWN 分类。新增 World identifier/plan-ref/bound 等确定本地拒绝分类要先于通用 UNKNOWN 字符串判断；真实远端 UNKNOWN 和 reconciliation 仍 fail closed |
| Book pre-prose Memo timeout execution successor | main 没有 `book_authority/execution_recovery.py` | 必须移植。仅历史会员 Memo 已知停止、settled、无成功输出/正文/acceptance/held lease；Kernel 取消旧 Chapter，Book 追加 request，ChapterGroup 更新引用；禁止复制子项运行状态 |
| failed Saga step successor 与候选修复 | main 没有 `command_kernel/step_successor.py` 和 Chapter contract/candidate recovery | 必须移植。覆盖 scene core、information flow、review scope、Revision length、Canon no-send capacity/protocol；保存旧步骤、成功 siblings 和实际模型费用，正常执行后续质量与接受门禁 |
| bounded execution window continuation | 分支 `execution_window.py` 与模板 v5 有独立增量 | 必须移植。只续未完成 root 的已授权工程窗口，保留 before/after、child timeout、no-progress、费用与真正 author deadline；不重新赋予 Provider 权限 |
| derived Canon/Quality revalidation | main 没有 `derived_step_revalidation.py`、`chapter_authority/derived_recovery.py` 等 | 必须移植 v6 精确纠错路径；旧 succeeded outputs 和 Effects 不重写。仅未接受 frontier、精确诊断、无已提交下游/held lease/UNKNOWN；Book acceptance 仍原子绑定 Canon、Narrative State 与 projection |
| Book reconciliation 与 superseded Effect 投影 | 分支 `production.py` 增加 v2 状态键、原终态 Effect 的版本化 supersession 解释 | 必须逐段移植；保留 main 的查询、取消与接受行为，supersession 必须能解析到同 scope 的原生 successor journal，不能仅凭 boolean 从 acceptance gate 排除旧 Effect |
| original Actor 与 scheduling Worker 区分 | main continuous phase executor 已校验 operator/input digest，worker 只持 execution lease；分支补 stage repair 时的 Actor | 保留 main，并使新增 stage/successor 命令使用原 Actor 及真实权限；不把 worker 提升为 author/operator |

退役是取消新运行的重复判定权，不删除旧分支提交、冻结 routing evidence、结果/receipt、旧 schema 或历史失败。所有历史身份仍可定位；“历史可读”不代表旧定义可以接收新模型调用。

## 新迁移身份和依赖

main 已发布的所有迁移文件保持逐字不变，特别是 0157 creation_continuation_control、0158 planning_capacity_causation、0159 planning_dead_letter_result_recovery。此次九项分支迁移都有非等价 schema/contract 增量，保留其迁移职责，但不照搬覆盖式 guard SQL。新身份统一使用集成日期 `20261007`，从当前 main head 连续编号：

| 旧分支历史 MIGRATION_ID | 新 MIGRATION_ID |
| --- | --- |
| `20261006_0157_planning_result_admission` | `20261007_0160_planning_result_admission` |
| `20261006_0158_planning_capacity_lineage` | `20261007_0161_planning_capacity_lineage` |
| `20261006_0159_planning_input_order_recovery` | `20261007_0162_planning_input_order_recovery` |
| `20261006_0160_optional_world_continuation` | `20261007_0163_optional_world_continuation` |
| `20261006_0161_gateway_result_revalidation` | `20261007_0164_gateway_result_revalidation` |
| `20261006_0162_stage_repair_policy` | `20261007_0165_stage_repair_policy` |
| `20261006_0163_failed_step_successor` | `20261007_0166_failed_step_successor` |
| `20261006_0164_execution_contract_continuation` | `20261007_0167_execution_contract_continuation` |
| `20261007_0165_derived_step_revalidation` | `20261007_0168_derived_step_revalidation` |

0160 DOWN_REVISION 必须为 `20261007_0159_planning_dead_letter_result_recovery`，其余逐项接前一个新 ID。模块文件也使用新身份。修正两处 VERSION_MODULES 的 import/注册、manifest migration_ids/head、当前操作文档和测试 imports/assertions。0165 原先从旧0160导入、0167原先从旧0162导入、0168原先从旧0164导入；新实现不再借旧覆盖式 SQL 的数组索引加 string.replace 来拼生产 guard，写出对应版本的完整明确 guard。

保留 main 0159 的 DEAD_LETTER + known success + no unresolved effects 条件，追加 runtime_continuation_id 身份不可变、同 project/workspace/Book/输入/来源与唯一索引约束。每个中间迁移 head 都须保留主线基础修复路径；不能等到最后一步才恢复它。main 0158 的 continuation cause guard 也须与新增 lineage 兼容；若确需调整，只能在新的前向迁移中加入精确分支，不得编辑0158。

schema 的合法原因逐类匹配：普通 raw repair、历史 cancelled release continuation、main pre-send capacity、raw-capacity preflight、route/input-order preflight、settled optional-world deferral；各自匹配对应证据。禁止用 `OR runtime_continuation_id IS NOT NULL` 替代来源和因果验证。新0161等 generation guard必须保留 main 对已合法注册 capacity cause 的兼容，不能误杀 main 的 FAILED_FINAL/DEAD_LETTER 零发送恢复。

保留旧分支 head、32 个提交和旧 manifest/SQL 的 SHA；交付证据内保存 old_id/new_id/source_commit/source_blob_hash、移植/覆盖/退役裁决及新 tree SHA。历史日志、P0 report、receipt、checkpoint 内旧 ID 不替换。旧分支迁移模块不加入新主线注册链；它们由原提交和证据映射定位。

### 已应用旧分支数据库

runner 使用完整字符串 ID，冲突包括顺序号复用、不同历史链以及同名 SQL 对象。`storage/migrations/runner.py` 当前 `pending_migrations` 只过滤已应用完整 ID；`run_migrations` 会执行 pending SQL，最后 `_status_from_rows` 才报告 extra。因此单纯改编号不能让旧分支库安全升级。

集成必须在任何 pending migration DDL 前比较 applied IDs 与允许的主线前缀，遇到 extra、hole 或旧分支链 fail closed；增加明确诊断和零业务变更的拒绝测试。正常支持 fresh 与 main0159→新0168。旧分支库保留 ledger、backup 和 restore evidence，报告独立历史链；不得 DELETE/UPDATE nf_schema_migrations、伪称已应用新 ID、自动改库或用 IF NOT EXISTS 掩盖 schema 差异。若要将该库业务记录转入主线，需要另行授权的精确转换任务，本工作包不执行。

## 唯一允许的实施与合并顺序

1. **固定来源与隔离。** 重新读取远端 SHA；若输入移动，停止按本编号执行，重新裁决。检查现有 worktree，选无无关变更的隔离 checkout，从固定 main 建立集成分支。保留原 PR133 head 和现有运行证据，不在原分支 rebase/force-push。列出全部132 paths并为32提交建立上述裁决映射，包含未产生文本冲突的自动合并文件。
2. **先固定迁移链及防退化反例。** 新建0160–0168与显式组合 guard，修正 registry/manifest，加入异链库预检。先在固定 main 上证明新增场景的缺口，并保留 main capacity/dead-letter/causal rejection 成功路径的保护测试；schema 先于依赖它的新 recovery 入口。
3. **整合 Planning 和路由。** main 已有结果恢复与 governed_repair 为基础；追加 Foundation admission、input-order、local gateway revalidation、可选 World 和每 stage bounds。新 route 只走一个原生事实构造与发送前复验路径；每stage语义使用新的receipt contract version，不能静默改变冻结 `planning-route-repair.v1` 的全局上限和判定。旧快照按版本兼容，不能改写冻结决策。保留 Context compression/fidelity 的原生门禁和真实 UNKNOWN 停止。
4. **整合 Chapter、Canon、Quality。** 移植失败 step、Memo execution replacement、候选 repair、窗口 continuation、derived revalidation、Pack/schema/Chapter版本与历史 sampling codec。Kernel 管 lifecycle，Domain 校验与提交，Book/Group 只调整其拥有的引用及协调状态；Provider I/O 在事务之外。
5. **最后接 creation 调度。** main 的 continue_creation/execute_creation_claim/取消及 lease guard 保持优先。所有新增 recovery 先检查原 cancellation、execution_probe、deadline、actor、有限 policy 和当前 frontier；重复 while recovery 纳入已有 tick/window/no-progress 控制。CLI与 BOOK_CREATION_ADVANCE worker走同一入口。避免新增hook在已取消Book上续窗口、重绑或生成工作。
6. **更新投影并验整棵树。** 按最终入口调整两份 canonical docs、reality-evidence、instruction/production/worker/test manifests 和 backend qualification semantic slices；禁止加交付历史文档或删除尚未解决的设计问题来取得绿灯。先定向回归，再完整 applicable P0。新migration/upgrade测试必须登记到 backend-qualification-manifest 的 migration_matrix，新语义测试登记到对应slice，否则完整门禁不能发现并认可它们。
7. **只合并完成整合的新分支。** 原 PR133保留为历史来源，不直接合并；从main发布替代integration PR并交叉引用133。按用户明确授权的发布步骤执行。测试冻结最终提交及tree/manifest hashes，发布或合并前比较最新base/head；任何代码或依赖变化都重新验证受影响范围。合并后对真实merge SHA重新运行完整适用矩阵，保留验证前后失败及独立运行目录；不能把integration head测试改称merge SHA测试。

此顺序为本工作包的唯一执行顺序。不能先把Chapter Pack/creative模板切到新版本再补其迁移与恢复门禁，不能先合原PR再在main补救。每阶段可用小提交评审，整合PR必须完整绿灯后才能合并。

## 必要定向回归

所有真实外部发送都替换为受控 transport/process fixtures，标记 SYNTHETIC 或 RECONSTRUCTED。测试真实 production assembler、Authority/UoW、PostgreSQL触发器与worker入口，不能仅mock最终成功结果。

| 范围 | 必须覆盖的判别场景 | 优先现有测试文件 |
| --- | --- | --- |
| 迁移和SQL guard | fresh；固定main0159含历史业务行→0168；每个新增中间head的主线保护；异链extra/hole先拒绝且零DDL/ledger改写；backfill与uniqueness；伪造registration/跨scope/cause；migration重跑 | `test_authority_migrations_postgres.py`、`test_authority_schema_postgres.py`；新增 dedicated migration upgrade test并登记 migration_matrix |
| Planning/路由 | main capacity2次上限与repair-origin compatibility；FAILED_FINAL/DEAD_LETTER成功receipt修复；非法raw生成新计费候选；合法Foundation无发送补准入；ordered hash不同但同role map；换artifact拒绝；stage allowance与global4上限；同模型内容修复不误计transport retries；metadata UNKNOWN、远端UNKNOWN、unsettled、independence、strict均阻断；dispatch证据漂移 | `test_planning_runtime_continuation.py`、`test_story_planning_runtime.py`、`test_native_planning_repair_routing.py`、`test_native_stage_repair_bound.py`、`test_cost_aware_routing.py`、`test_authority_worker_execution.py` |
| World | typed transition/StoryTime、精确Arc/obligation refs；main因果拒绝复现及Director receipt结算；原action复用；known identifier checkpoint不重发；OPTIONAL/DISABLED DEFER与REQUIRED/accepted commitment拒绝；DEFER不写accepted事实 | `test_world_causal_preparation.py`、`world_causal_production_support.py`、`test_synthesis_formation_postgres.py` |
| Foundation/gateway | 原Context/author projection和完整冻结schema；literal null可本地复核；result/process/hash/path漂移、缺receipt、未结算、持有lease、foreign Book及UNKNOWN全部拒绝；幂等恢复0新增send，仍待Story Design审批 | `test_synthesis_formation_postgres.py`、`test_external_effect_runtime_postgres.py`、`test_codex_execution_evidence.py`、`test_work_foundation_contract.py` |
| Chapter/Canon/Quality | Memo known timeout successor保留旧attempt/费用；scene-core复用Memo/Context；information/review/length修复输入与counter；execution-window author deadline拒绝；Canon no-send capacity、nullable schema、严格canonical decode/support taxonomy；derived revalidation保留旧成功结果、只修未接受frontier；accepted/UNKNOWN/live lease/downstream commit拒绝 | `test_book_execution_recovery.py`、`test_derived_step_revalidation.py`、`test_chapter_authority_definitions.py`、`test_chapter_provider_output_contracts.py`、`test_grounded_canon.py`、`test_creative_quality_admission.py`、`test_work_quality_semantics.py`、`test_work_realization_contract.py` |
| 原生纵向和creation | start→formation→opening→planning→chapter→review/revision→internal acceptance→export→Book cursor；组件重建再continue不重复successful send/accepted chapter；非首选candidate；worker原actor绑定；cancel抢在recovery前；lease丢失、deadline/no-progress恢复停止；reconcile同状态幂等且不同版本不冲突 | `test_synthesis_formation_postgres.py`、`test_creation_cli_postgres.py`、`test_book_to_chapter_authority_vertical_postgres.py`、`test_creation_coordination.py`、`test_author_supervised_policy_postgres.py` |
| Context Router和旧合同 | overflow→compress→fidelity→Draft；reject/error/timeout/UNKNOWN及恢复；历史模板v1-v6和configure定义；原3.8Memo timeout不改写；Chapter sample/reference历史codec；Pack历史合同与新部署绑定、realization和其他任务版本相互匹配 | `test_context_compression_provider.py`、`test_context_compression_routing.py`、`test_creative_execution_template.py`、`test_chapter_sample_contract_versions.py`、Pack validator/materialization/longform profile测试 |

优先保留分支现有纵向node：`test_native_retained_valid_result_admission_without_another_provider_call`、`test_native_failed_final_input_order_successor_preserves_terminal_history_and_counter`、`test_native_settled_optional_world_failure_continues_without_repeating_calls`、`test_native_rejected_null_schema_result_revalidates_without_resend_then_accepts`、`test_native_world_repairs_do_not_exhaust_rejected_chapter_plan_stage`、`test_native_known_preprose_memo_timeout_successor_preserves_history_and_accepts`、scene-core/information/review/length四项successor；它们在整合树上重新执行，旧测试记录不转移。还必须补两边同场景交叉保护，不能仅各跑原有正例。

完成门禁以最终 `docs/runtime-operations.md` 为准：

```bash
P0_PROFILE=local P0_EVIDENCE_DIR=/tmp/novel-forge-pr133-integration-p0 \
  make p0-backend-qualification
```

独立命名的caller-owned disposable PostgreSQL必须有pgvector支持，证据目录每run使用唯一身份。P0完整13阶段为source-preflight→documentation-reality→static-and-manifests→pytest-backend→postgresql-start→migration-fresh→migration-compatibility→pytest-postgresql-integration→migration-head→query-plan-release→compose-runtime→resource-cleanup→evidence-finalization。若触及API/控制台交互，增加实际Editor/API受控操作；不把普通后端P0当成UI或真实Provider证明。

## 硬停止和最终验收

`CURRENT_PROVEN_INVARIANT` 保留：Authority ownership、immutable terminal history、exact identity、UNKNOWN reconciliation、source isolation、atomic Book acceptance。迁移编号与当前注册head是固定SHA下的 `CURRENT_RUNTIME_FACT`；模板mode、World optionality、stage/window/capacity限额是有版本的 `CONFIGURABLE_POLICY`；旧模板/旧receipt读写边界是 `HISTORICAL_COMPATIBILITY`。两套路由如何兼容冻结证据以及异链库转换在实现通过前属于 `UNRESOLVED_DESIGN_CONSTRAINT`，不能从常数或类的存在推定已关闭。

立即阻断：main旧migration有byte变化；旧分支ID进入新registry；组合guard丢失main DEAD_LETTER或capacity cause保护；新恢复让UNKNOWN/strict/accepted数据越权；cancel或lease已失仍续执行；历史receipt改SHA或ID；费用/repair counter清零；fixture混入real统计；真实Provider被调用。

交付必须含：固定base/source/final commit/tree；32提交和132路径裁决映射；九项old/new migration及source blob映射；全部17文本冲突和24重叠路径的语义解决结果；新fresh/upgrade/negative回归证据；完整P0及cleanup结果；source-bound历史证据单独列出；真实Provider=`NOT_RUN`；merge后验证用独立merge SHA/run并明确PASS/FAIL/BLOCKED/NOT_RUN。任何已复现基线失败必须在固定main上留证，不能通过放宽门禁或删掉失败来宣称完成。

## 固定实现证据

- [main迁移注册表](https://github.com/yuan2go/novel-forge/blob/f9e1ee5e115fd47b8bb9d97a35aa2813b7e04609/src/novel_forge/storage/migrations/versions/__init__.py)
- [main DEAD_LETTER SQL guard](https://github.com/yuan2go/novel-forge/blob/f9e1ee5e115fd47b8bb9d97a35aa2813b7e04609/src/novel_forge/storage/migrations/versions/v20261007_0159_planning_dead_letter_result_recovery.py)
- [main capacity与causation](https://github.com/yuan2go/novel-forge/blob/f9e1ee5e115fd47b8bb9d97a35aa2813b7e04609/src/novel_forge/modules/story_planning_runtime/runtime_continuation.py)
- [main Router内容修复](https://github.com/yuan2go/novel-forge/blob/f9e1ee5e115fd47b8bb9d97a35aa2813b7e04609/src/novel_forge/modules/production_execution/cost_routing.py)
- [main creation worker与取消边界](https://github.com/yuan2go/novel-forge/blob/f9e1ee5e115fd47b8bb9d97a35aa2813b7e04609/src/novel_forge/modules/book_authority/creation_runtime.py)
- [main迁移runner](https://github.com/yuan2go/novel-forge/blob/f9e1ee5e115fd47b8bb9d97a35aa2813b7e04609/src/novel_forge/storage/migrations/runner.py)
- [分支Foundation结果准入](https://github.com/yuan2go/novel-forge/blob/ad1c229d4b17db45fa14c73dcc6569e8655c82c9/src/novel_forge/modules/story_planning_runtime/result_admission.py)
- [分支input-order与route preflight](https://github.com/yuan2go/novel-forge/blob/ad1c229d4b17db45fa14c73dcc6569e8655c82c9/src/novel_forge/modules/story_planning_runtime/preflight_continuation.py)
- [分支每stage repair](https://github.com/yuan2go/novel-forge/blob/ad1c229d4b17db45fa14c73dcc6569e8655c82c9/src/novel_forge/modules/story_planning_runtime/stage_repairs.py)
- [分支旧迁移链](https://github.com/yuan2go/novel-forge/blob/ad1c229d4b17db45fa14c73dcc6569e8655c82c9/src/novel_forge/storage/migrations/versions/__init__.py)
- [PR 132](https://github.com/yuan2go/novel-forge/pull/132)；[PR 133](https://github.com/yuan2go/novel-forge/pull/133)。
