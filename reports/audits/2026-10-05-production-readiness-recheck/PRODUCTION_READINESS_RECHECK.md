# Novel Forge 生产链重新复核

> HISTORICAL_SNAPSHOT / NOT_RUNTIME_AUTHORITY：以下结论仅对应文内冻结身份；不是最新 main、运行实例或本工作包的结论。原证据包保留。

复核时间：2026-10-05。只分析和必要离线验证，未改生产代码、未启动生产服务、未接生产数据库、未调用真实 Provider。

**需要收紧上一轮的结论：七项目标问题在新默认修复快照中已完成工程修复；整个正式生产链尚不能判定为已修复或可以直接开工。** 当前存在可复核的压缩任务路由缺口，而且本轮起点的 main 未含补丁，运行版本未验证。不是断言项目没有构建小说的能力，也不是推定真实模型质量差。

## 版本核对

| 基线 | 实际身份 | 本次判断 |
|---|---|---|
| 远端 main | `f34eee742e93598db887afddf0f121f4e99e1fd7`，本轮起点冻结 | 该冻结版本未包含上一轮本地补丁，不能当作已修复 |
| 隔离修复版本 | main 基底 + diff SHA256 `1a3824216a4cd1928af54a3f4bd0baea7dcf9900de938a1c31c2fb2dd3e79bb6` | 当前补丁及56个文件 hash 与上一轮最终验证完全一致；仍未提交 |
| 原用户工作区 | `ceb69fa2ff1c56f07005154bb5797616e933e8c2`，`codex/wp02-author-approved-run` | 未切分支、未改跟踪文件；不是上述新版本 |
| 活动应用/数据库资产 | NOT_VERIFIED | Docker 只观察到 Novel Forge 数据/对象存储及测试数据库容器，未据此推断不存在其他应用进程或远端实例；未读取生产 DB、密钥或私人作品 |

结束时远端 main 更新为 `f60725c70d80b04eb82dafa1f62393cab91ef2e7`。该新提交未读取或运行，本轮没有把新版本证据并入冻结快照结论；**最新 main 的修复状态为 NOT_VERIFIED**。

`baseline.json` 和此前 `snapshot-identity.json` 固定以上身份；不能把某个 main SHA 代替含补丁的完整身份。

## 五项结论

| 项目 | 结论 | 依据 |
|---|---|---|
| 七項目标修复闭环 | PASS，新默认修复快照的工程范围 | 补丁未漂移；44项直接反例本次重跑全部通过；逐项复读新方法、版本选择、适用性与普通修订合同 |
| 当前作品输入的控制权 | PASS，已覆盖方法装配/Schema/基线传递 | 原生 Foundation 最终输入、当前候选 baseline、已选承诺失败与未选方法有效替代；真实模型是否遵守仍 NOT_VERIFIED |
| 正式生产功能整体 | **FAIL，条件必需分支存在硬缺口** | 常规作者→方案→计划→正文→审读修订→接纳→续章有 MOCK_E2E；正式 Router 的上下文压缩/保真任务直接失败，见下面 PR1 |
| 当前实例已经使用修复 | **NOT_VERIFIED；冻结 main 未集成；新 main 未验证** | 新 Planning/Chapter/Longform 资产尚无本轮生产激活或部署身份，不能仅凭仓库文件判现场已升级 |
| 真实小说效果及长篇连续生产 | **NOT_VERIFIED** | 无该修复版本的 REAL_RUN/REAL_CAPTURE；脚本三章、预设评价及 mock 正文不能证明文学质量 |

证据状态最高 `EXECUTABLE`，其中正常链是 `MOCK_E2E`。未升级为 `QUALIFIED` 或 `PRODUCTION_PROVEN`。

## PR1：上下文超限后的正式任务路由仍失败

- 分类：原有生产功能缺口，上一轮七项修复未覆盖；严重性高，证据强度强 STATIC + OFFLINE。不是新修复引入的回归：`cost_routing.py` 与固定 main 原文件字节相同。
- 触发：`draft-context-profile-v4` 在可压缩历史超过冻结预算、精确必需资料仍可容纳时，进入正常压缩链；启用正式 Provider Router。production 环境默认启用 Router，test 环境默认不启用。
- 实际链：`handlers.py:1290` 构造压缩回调，`domain_handlers.py:409` 调用 `compile_task_context`；`task_compression.py:171,235` 在超限时请求 `context_compress`，随后请求 `context_fidelity`。`execution_gateway.py:1057` 把该 stage 原样作为 `task_type` 交给正式 Router；`routing_runtime.py:1015` 调用 `CostAwareRouter.explain`；`cost_routing.py:97,187,776` 的 taxonomy 未登记两个任务，抛出错误。
- 配置证据：`provider_control/composition.py:43` 的 production 默认 Router 选择；`authority_dependencies.py:382,1278` 按此建立正式 Router。
- 本次反例：`reproduce_router_gap.py` 使用实际 `CostAwareRouter`，分别得到 `ROUTING_TASK_POLICY_REQUIRED:context_compress` 和 `ROUTING_TASK_POLICY_REQUIRED:context_fidelity`。再通过实际 `compile_task_context` 的超限回调复现两条错误；后一条用明确的合成压缩结果到达 fidelity。零发送、零 DB 连接。
- 正对照：普通 `draft` 可以取得已定义任务策略，不抛 unknown-task 错误；本脚本合成基准不构成真实生产资格，因此它的最终路由状态 BLOCKED 不是 Draft 已可真实发送的证明。
- 影响：预算内 fast path 可正常通过；所以上一轮三章成功与此缺口并不矛盾。后续超限时会在发送前停止，不能判无限期或所有合法连续生产可用。没有声称每本书第一章都必然失败。
- 最小修正：在既有 Router 中为这两个任务补齐一致的任务策略、质量反馈/资格和策略校验身份；按任务真实职责选择风险与证据，不能借普通 review 身份代替。
- 关闭证据：开启与 production 一致的 Router，在隔离正式 Chapter/Context→Provider 边界验证超限→压缩→fidelity→Draft 装配；证据不足/错误保真仍阻断，并保留失败恢复及同书版本身份。只在合成 callback 中返回预置成功不足以关闭。

本问题此前在旧 Context 审计中出现过，本轮重新从当前代码与离线反例确认；没有把旧记忆结论直接当当前事实。此次不实施修复。

## 测试失败及证据有效性

本轮最小扩展检查为五个相关文件：**145 PASS、1 FAIL、0 skip**。七项直接残留反例文件的44项全部通过。失败不能隐藏或与旧510项相加后宣称全绿。

失败：`test_task_context_admission.py:9` 的 `test_task_dependency_admission_is_wired_only_for_the_frozen_v4_profile`。该 fixture 与 `_intent()` 仅给 `accepted_through_chapter=8`；新合同 `context_compression_provider.py:13` 要求同一接纳边界的 Canon、Narrative State 精确版本。`orchestrator.py:929` 正确 fail closed 为 `ACCEPTED_BOUNDARY_INVALID`。

仓库外 `verify_boundary_fixture.py` 只为候选、Intent/Memo 补齐两个 snapshot ID，保留原测试全部断言，复验通过；未修改 repository fixture 或生产守卫。生产接纳 `book_authority/production.py:1589` 正常保存这两个版本，此前三章 mock 接纳/续章亦实际消费它们。因而当前证据把这项分类为**低严重性测试合同同步缺口**，不当作已证明的生产死结。最小修正是同步这个测试的合法前置，并保留“缺失/错版本必须拒绝”的反例。

本轮另核验新 history projection 的私有/审读资料过滤路径：相关清理测试通过，当前 `accepted-writer-history.v2` 在非 State 与嵌套结构同样清洗。未沿用旧审计的泄漏结论，也不扩大为日志或提示注入审计。

上一轮 PostgreSQL 六项记录与当前完整补丁身份一致，本次检查其 XML、退出码、测试环境与断言：一章作者全链、纯建议跨章三章、不改正文/SceneSlots、结果修复、旧运行恢复、Longform materialization/回执恢复、观察型零增量等工程证据有效。此次没有重复启动 DB 全套用例。

但这些测试明确配置 `environment=test`、`scripted_provider_v2`、`NOVEL_FORGE_TEST_ALLOW_SCRIPTED_NARRATIVE_EVALUATION_FIXTURE=true`，没有开启正式 Router；生产 release/Provider 输出、独立语义评价是测试构造。因此它们不能关闭 PR1，也不能代替现场资格、真实文学判断或正式模型路由验证。

最初的 Router 超限复现脚本误用了字面的 backslash-n，导致单一必需段落超预算而先被正确拒绝；外部脚本改成原用例的真实段落边界后复现路由错误。错误说明保留在 `evidence/reproducer-first-error.txt`，没有更改生产预算或守卫来造通过。

## 能否开展小说构建

1. **准备作者输入、题材方向、人物/世界观要求和作品方案：可以。** 软件存在且接通相应正式入口；这些准备也不要求立即支付模型调用。
2. **认为当前 main 或当前实例已经修复，直接开始真实整本/长期自动生产：不具备 GO 条件。** 冻结 main 未含补丁，本次修复快照的压缩 Router 仍有确定缺陷，实例资格未知。
3. **使用新修复版本开展有限真实试产：可以作为下一阶段，但先完成下面的最小补齐。** 缺少真实样本不是必须继续增加 Agent 或大规模重构的理由。

最低顺序：

- 先修 PR1，并同步上述过期 fixture，补一个真正启用 Router 的超限与失败恢复验收。
- 将固定补丁集成到拟运行的提交/构建，核对新 Planning 1.18/Pack2.10、资格 Profile3、BookDesign v7、Chapter3.7/Pack2.11/Template9、Longform Pack1.3/window2 的编译、激活和精确绑定。旧排队/冻结任务不得冒称已使用新合同。
- 只读确认该 Book 的正式资格或明确作者监督授权、Provider/model/容量、预算、资产与 accepted state 能通过实际 preflight。
- 在另有明确真实调用授权与预算后，从少量相反方向作品中选择一个两章试产：保留作者输入→最终请求→正文→审读/必要修订→准确稿件接纳→第二章消费；第一章先人工看可读性再继续。真实上下文超限分支可先用隔离工程验证，无需为触发它付费生成整本。

此次分析未发现必须重建全系统的理由，但**至少一个明确生产功能缺口仍要修**，不能继续沿用“没有额外修复工作包”的宽泛说法。上一轮该表述只能限于所列七项和当时覆盖。

## 复核材料

- `baseline.json`：本次起止基线与差异身份；`coverage.json`：PASS/FAIL/未知范围。
- `evidence/router-gap.json`、`router-gap-native-final.log`：实际 Router 与 Context 超限反例；`reproduce_router_gap.py` 可离线复现。
- `focused-reanalysis.log/xml`：145 PASS + 1 FAIL 原始结果；`evidence/boundary-fixture.json`：仓库外合法前置反证。
- `evidence/source/`：14个必要调用/配置/测试源原件及 hash；`evidence/main/`：main 对照原文；`evidence/reused-evidence.json`：既有工程证据身份，明确没有重跑 PostgreSQL。
- 此前完整 Prompt/Skill 原文与七项补丁仍位于 `/Users/yuan/Documents/Codex/repairs/novel-forge-work-intent-20261005/`；此次无代码修改。
