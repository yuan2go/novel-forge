# Novel Forge PR 133 最终集成工作包

从固定 main 移植必要恢复增量，保留 native production closure；原 PR133 仅为历史来源。本文件描述当前未提交集成树及剩余执行步骤，不授予真实 Provider、生产库或既有 Book 执行权限。

## 固定来源与证据

- worktree：`/Users/yuan/.codex/worktrees/pr133-native-integration/novel-forge`。
- main：`f9e1ee5e115fd47b8bb9d97a35aa2813b7e04609`。
- PR133：`ad1c229d4b17db45fa14c73dcc6569e8655c82c9`；共同祖先：`e2064ede68920f680204c40486bf69f1901fb770`。
- 原始裁决：`implementation/source-adjudication.json`，132 路径、32 提交、24 重叠、17 文本冲突及九项迁移映射保持原判定；追加的 `integration_forward_fixes` 单独归因集成前向修复。
- 已发布迁移核对：`implementation/published-migration-byte-proof.json`；固定 main 的全部 160 个 `v*.py` 文件与当前 worktree 字节一致。注册表允许追加；已发布 migration body 不可修改。
- 最终 commit/tree 尚未冻结。分项工程验证与原分支历史 PASS 不构成最终 P0、真实 Provider 或 merge SHA 验证。

## 已实现的当前增量

1. 新迁移链 0160–0168，保留 main 0158 capacity cause 和 0159 DEAD_LETTER/known-result/no-unresolved-effect 保护；runner 在 pending DDL 前拒绝异链和 hole。旧分支数据库不自动转换，不改写 ledger。
2. Foundation 补准入在 mutation UoW 复验完整 source/repair lineage 的 SETTLED reservation、成功 Effect 与无 HELD lease；成本估计UNKNOWN但reservation SETTLED允许。显式validation contract1.19和v4Candidate/provenance保留原请求。原PR133 SQL反例不阻断，新guard拒绝，11项定向PASS只作工程证据。Planning 增加保留合法 Foundation 准入、零发送 input-order/route preflight、本地完整 gateway 输出复核、受策略约束的 World deferral、每阶段有界修复。新发送只走 `governed_repair`；首Evaluator无历史dispatch不构造repairreceipt。受控World故障fixture显式选择REQUIRED，不改变config默认DISABLED；显式template.v2/routing.v1仍使用原生receipt v1（current1.19 input-order单项PASS129.36s）；只有授权template.v4/routing.v2使用receipt v2（stage3单项PASS150.95s）。receipt v1 保持历史语义，v2 绑定 stage/ordered hashes/role map，计数跨 continuation 不清零。UNKNOWN、strict、已接受 commitment 和独立 actor experiment 不被 deferral 放行。
3. Chapter/Canon/Quality 增加原生 failed/derived successor、已知 pre-prose Memo replacement、有限 execution window 与候选纠错；只允许精确 live/unaccepted frontier，旧终态/成功结果、账务和 accepted facts 不重写。
4. 当前前向合同为 Planning 1.19.0 / Pack 2.11.0 / Prompt v9 / Mission v4 / runtime projection 3.0.0 / activated plan v3 / work-v4；Chapter Plan 3.9.16 / Pack 2.26.0 / authoritative plan v5 / draft view v4。此前发布合同按原身份读取，不改写其证据。
5. 冻结 World 的独立评估只在 exact project/Book/World/hash、独立成功 PASS、原生 APPROVE 与 ACTIVATE 完整匹配时进入 Quality；审批 asset 追加为冻结输入。生产层仅读取和校验保留 process/result 文件；Planning 承担语义复核，API composition 注入原生 receipt callback，策略修改由 owning Authority 命令承接。
6. creation 在恢复钩子间保留原 actor、取消、lease、deadline、有限窗口及 no-progress 控制；Book/Group 只协调其拥有的引用。
受控 synthesis fixture 仅按实际 execution_contract_version 1.19 选择 Mission4/serialization_function，历史请求仍为 Mission3；该 fixture 修复与 World canonical identity 修复单独标为 integration-only。
Plan 3.9.16 使用精确 semantic 映射，未来 3.9.17 不自动继承 work gate；fallback manifest 按 semantic identity 保留原 style_policy_version_id。当前 Planning1.19 的 Foundation v4 task/envelope/schema 身份支持 RFC6901；历史6roles×1.17/v2、1.18/v3共12schema hashes和JSONPath reader精确保留。partial-alternative fixture 改用无合法前缀的 field_path 保留一失败 alternative/两次调用；固定 main 原测试 PASS 日志单独保留。
7. canonical docs、WIRED 拓扑、instruction/production/test/qualification manifests 已投影实际入口。新增 migration/history/creation/frozen-World/PRIMARY-Context 精确身份反例已登记；Optional World 反例在既有 `test_creative_execution_template.py`，没有另造文件。

## 历史迁移映射

| 旧分支身份 | 集成身份 |
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

0160 依赖已发布 main0159，其余依次依赖前一项。旧提交、旧 manifest/SQL blob、旧 run/receipt/checkpoint 的身份保留于来源证据；旧 ID 不加入当前注册链。

## 仍须按唯一顺序执行

1. **隔离固定来源 → 迁移与保护反例 → Planning/路由 → Chapter/Canon/Quality → creation 调度。** 这些实施阶段已形成当前树。最终冻结前检查全部差异、复核 132 路径与额外前向修复归因。不得整包覆盖原分支；发现 main 旧迁移有任何字节差异立即停止。
2. **投影及完整验证。** 未发布 0163/0165/0167/0168 OPTIONAL SQL guard 已完成十-head定向PostgreSQL矩阵（10 PASS，25.65s）；完整receipt/scope保护保留，该范围不等于最终P0。Binder已在raw validation前绑定原Context id/hash/selection与Pack，失败checkpoint不再丢失或混淆多World stage Context；6项定向PASS仍只证明该范围。当前World-primary首节点PASS，剩余当前World与三causal节点仍在执行，须观察结果后再冻结。停止并行修改，stage 最终树、刷新 checked reality tree digest，记录精确 commit/tree/manifest hashes。先清除最终树的静态/定向失败，再执行 `docs/runtime-operations.md` 的完整适用矩阵。已有分项日志仅作范围内工程证据；固定 main 的 18 FAIL/79 PASS、Book 错误码 FAIL、legacy pre-DB FAIL，以及集成 99 PASS fixture repair 均保留，不能删除旧 FAIL 或据此宣称最终资格。
3. **替代集成 PR。** 完整矩阵成功且 cleanup 完成后，从固定 main 发布替代 PR，交叉引用 #133 和来源映射。保留原 #133，不直接合并其树、不 force-push 旧分支。发布前重新核对 remote base/head；移动则重新审计受影响范围。
4. **merge SHA 独立验证。** 在真实合并提交的新隔离目录和新 evidence run 下重跑完整适用矩阵，分别记录 PASS/FAIL/BLOCKED/NOT_RUN。集成 head 的报告不得改名为 merge SHA 报告；只有此阶段完成才报告合并后工程验证成功。

最终冻结提交的 P0 入口：

```bash
P0_PROFILE=local \
P0_EVIDENCE_DIR=/tmp/novel-forge-pr133-p0-<unique-run-id> \
make p0-backend-qualification
```

按当前 runtime operations 配置 caller-owned disposable PostgreSQL/pgvector 和受控 transport/process fixtures；不得对生产库或其他运行中的测试库 truncate。完整 13 阶段必须含 fresh migration、compatibility matrix、PostgreSQL integration、head、query-plan release、compose runtime、cleanup 和 evidence finalization。任何冻结后变更需重跑受影响定向范围及完整适用门禁。

## 最小必要定向范围

- 迁移：`test_migration_history_admission.py`、`test_migration_history_admission_postgres.py`、`test_creative_validation_integration_upgrade_postgres.py`；fresh/main0159→0168、每个新增中间 head、foreign/hole 零 DDL/ledger 改写、UNKNOWN/reservation/原 ledger timestamp。
- Planning/路由/World：容量与 DEAD_LETTER 主线保护、Foundation 无发送补准入、ordered-input/role-map、receipt v1/v2、stage/global bounds、settled gateway/process hash、OPTIONAL/REQUIRED、未知或 retryable 状态拒绝、原 action/Director 因果证据；完整 BLOCKED plan 的 canonical JSON identity 允许 JSONB tuple/list 表示差异，任何 requirement 内容变化仍拒绝。
- Chapter/Canon/Quality：已知 Memo timeout、failed/derived successor、accepted/live lease/UNKNOWN/下游提交拒绝；当前 Plan→ExecutionIntent 序列化；`test_quality_frozen_world_foundation.py` 的缺 proof/foreign/FAIL 反例。
- creation/native vertical：原 actor、取消/deadline/lost lease 在钩子间发生、重复恢复有限 bounds、重建不重复 successful send/accepted cursor；Context compress/fidelity、旧 sampling/Pack/schema 身份继续兼容。

## 硬停止与交付

停止条件：旧 migration body 变化、旧 ID 注册到主线、UNKNOWN 或费用/计数被清除、strict/accepted frontier 越权、丢失 cancel/lease 保护、冻结合同被静默改写、fixture 被计入真实统计、真实 Provider 调用。

交付：base/source/final/merge SHA 与 tree；原 132/32 裁决及前向归因；九项旧新迁移 blob 映射；160 项已发布 migration 字节证明；最终完整 P0 与 cleanup；替代 PR；merge SHA 独立 run。真实 Provider 仍为 `NOT_RUN`，当前新增恢复投影维持 `WIRED`，不得升级为生产或文学质量证明。
