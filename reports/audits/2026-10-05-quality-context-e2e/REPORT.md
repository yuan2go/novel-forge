# Work Intent Quality Semantics + Context Compression Routing + Production E2E Closure

本报告是本次工程证据，**不是运行时 Authority、完整 backend qualification 或文学质量证明**。

## 结论与证据边界

| 完成项 | 结果 | 证明范围 |
|---|---|---|
| QUALITY_SEMANTICS_CLOSED | PASS | STATIC / OFFLINE / MOCK_E2E；作品适用性、阈值、verdict、calibration 和动作分离 |
| CONTEXT_COMPRESSION_PRODUCTION_READY | PASS | 正式 Router、admission、Kernel Effect、独立 fidelity、重建及失败闭环；MOCK_E2E |
| AUTHOR_INTENT_PROPAGATION | PASS | 精确冻结输入、Foundation/Plan/Provider 参数、baseline、Quality 与接纳绑定；MOCK_E2E |
| FORMAL_PRODUCTION_E2E | PASS | 三作品各三单元，正式作者命令、Formation、Opening、Book/Chapter worker 与接纳 |
| ACCEPTANCE_AND_NEXT_UNIT | PASS | 原稿/限定修订接纳、原子投影、next-unit 精确状态读取、并发/回滚不变量 |
| RECOVERY_PATH | PASS | schema/qualification replacement、native dispatch recovery、UNKNOWN 禁止盲重发、frozen replay |
| LEGACY_ASSET_SAFETY | PASS | 历史资产保留；不洗旧 evidence；新入口拒绝旧污染投影和缺少适用性绑定的 Style |
| REAL_PROVIDER_VALIDATED | NOT_VERIFIED | 未获付费 Provider 授权，实际调用数为 0 |
| CREATIVE_QUALITY_PROVEN | NOT_VERIFIED | 模型替代件、短小工程稿、fixture 校准标签不能证明文学质量 |
| PRODUCTION_READY | PASS | **本工作包工程范围**的正式链路就绪；证据上限 MOCK_E2E，无已知未修复工程阻断 |

`PRODUCTION_READY` 不代表部署或真实模型资格。冷启动 Router 仍拒绝没有独立资格/容量/预算/授权的模型；本次没有写入虚假真实 benchmark 或激活任何真实生产作品。能力达到本包已验证的 CODE_EXISTS / WIRED / EXECUTABLE；未升级完整矩阵要求的 QUALIFIED。没有 REAL_CAPTURE、REAL_RUN，也不声称 creative/long-form quality proven、PRODUCTION_PROVEN 或稳定高质量长篇生成。未运行无关全量矩阵，未升级 architecture 中已有完整资格证据的等级。

## 固定版本与工作区保护

- 起始远端 main：`4948d9b3a1ca22a78daffb4f4ab1cbf46180ac52`。
- 用户原分支：`codex/wp02-author-approved-run`；原 HEAD：`ceb69fa2ff1c56f07005154bb5797616e933e8c2`。
- 原未提交状态：只有 approved-start 下既有未跟踪 receipts/logs；完整路径列表见 `baseline.json`。没有 reset、stash、覆盖、删除、移动或纳入这些文件。
- 实现分支：`codex/work-intent-context-e2e-20261005`；隔离 checkout：`/Users/yuan/.codex/worktrees/work-intent-context-e2e/novel-forge`。
- 最终实现提交：`a57b8dbb959f790c606c59c98fccfbe863434a40`；实现树：`sha256:3b9e80602491186094d5caf94d0556fb65210ba8dc05f9cbc29abc7e0601ff36`。交付 HEAD 是包含本报告的后续本地证据提交，完整 SHA 在最终答复中给出；没有 push/PR/merge。
- `implementation-identity.json` 保留代码、测试、Pack、Prompt、Skill、manifest 文件身份。MOCK 运行内部声明的 release SHA 为人工测试值 `eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee`，不能把它当成真实部署提交或资格快照；报告所绑定的 Git/实现树另行明确。

## 文档先清理，再实现

先阅读了 `docs/README.md`、current-system、runtime-operations、reality projection、生产/worker/migration/instruction/test manifests，以及上一轮两个审计目录和相关 proposals，并沿真实装配核对作者输入、Foundation、Planning、Quality、Revision、Context、Router、Book acceptance 与 recovery。起始报告中的默认入口与 fixture 能力不等于正式路由可执行。

实际更新：

1. `docs/current-system.md`：先记录起始缺口及工作边界，再同步新版本、作品/公共系统控制关系、明确迁移阻断与证据上限。
2. `docs/runtime-operations.md`：明确 context 两任务起始无 Router policy、新 taxonomy/qualification/feedback；更新 Pack/Chapter/sampler 与 Style 迁移操作要求。
3. `reports/audits/2026-10-05-production-readiness-recheck/PRODUCTION_READINESS_RECHECK.md`、`2026-10-05-work-intent-engineering-delivery/ENGINEERING_DELIVERY.md`：添加历史范围/非当前 Authority 提示，原报告和历史归档保留。
4. 四个 `architecture/proposals/*.md`：仅复核并更新实现 baseline；保持原未决/部分实现状态，不把本包冒充完整 proposal 交付。
5. `architecture/reality-evidence.json`：更新 projection_source 实现树身份，不提升历史 qualification / production 等级。
6. `architecture/manifests/test-manifest.yaml`：明确新增测试 proof ceiling。没有新增 canonical doc、Skill、Agent Authority、Router 或平行生产链。

旧 Prompt/Skill/Schema、旧章节/Style/sampler codec 和已发布 migrations 均未删除或改写。

## 工程方案与实际修改

完整代码/测试文件列表见 `CHANGED_FILES.txt`，交付文档/证据变更见 `DELIVERY_MANIFEST.json`。核心改动：

- **Quality Authority**：`work_semantics.py` 统一 work-quality.v2；domain/context_views 消除 threshold 反向决定适用性、分数洗 verdict/calibration 和旧证据重解释。accepted_projection/longitudinal 保留已接纳 v1/v2 可读性。
- **Quality → Revision**：content_quality_loop 的 aggregate v5 保留独立字段、完整维度和精确 baseline/target/policy。辅助 Review 的未校准分数为零权重；其失败事实保留 veto 并要求取证。仅校准、定位且属于可修复范围的失败进入 LOCAL_REPAIR。aesthetic/UNCERTAIN 不授权正文修改，固定 Revision 节点可 empty edits，原稿仍可获接纳。
- **Style/Plan**：Foundation style compile 2.1.4/v4 绑定 Book 与批准来源；runtime projection 2.0.0 只复制作品实际选择。Draft Plan v3、ExecutionIntent、baseline 和所有下游保存精确 selected_values，不能只保留 APPLICABLE 标志丢掉方法内容。
- **版本门**：新 Chapter 3.8/author3.8 的 ExecutionIntent 必须使用带 work_applicability 的 selected Style v4；显式 Preparation override 也必经此门。旧 style 报 STYLE_PROJECTION_MIGRATION_REQUIRED；旧污染计划投影报 CHAPTER_PLAN_PROJECTION_MIGRATION_REQUIRED。旧 work Quality 3.6/3.7 在新实现里报 QUALITY_FROZEN_SEMANTICS_MIGRATION_REQUIRED，既不偷换 Prompt，也不把旧 v1 evidence 算成 v2 PASS。
- **生产 Context**：cost_routing/routing_bootstrap 增加正式 context_compress/context_fidelity HIGH-risk taxonomy，复用质量约束、Provider admission、budget/timeout/retry 和 Kernel。
- **独立 fidelity / feedback**：task_compression 保存 source/required/selected/causal/knowledge/attribution 与所有 fidelity assessment。context_feedback 从 native Dispatch、VERIFIED Receipt、ModelCallLog 和成功 Context 交叉核验；按 generation/稳定 ID 选证据，保留失败重试和首次 fidelity failure 的分母，fixture 调用不成为真实资格。不能让 compressor 自证或让 later success 抹掉 prior failure。
- **Book/Group**：work-requirements Group 输入走自己的矩阵规则，不套公共 reward/hook 同质性门；现有 Book acceptance 原子事务仍是唯一接纳 Authority，次章读取 exact accepted snapshots。
- **采样兼容**：新 sampler 2.2/2.3 同时保存 sampler execution identity 和 exact native source semantics；旧 2.0/2.1 不跟随新的全局 Chapter 常量改变 source policy。

约束分类：接纳原子性和身份拒绝在本次状态测试范围内属于 CURRENT_PROVEN_INVARIANT；版本/路由装配属于 CURRENT_RUNTIME_FACT；阈值、HIGH-risk 的 20 effective samples、保守下界、预算/timeout 属于 CONFIGURABLE_POLICY；旧资产属于 HISTORICAL_COMPATIBILITY。真实 fidelity、模型校准与文学效益仍未验证，不能从现存常量推成终极架构或文学规律。

## 修复前反例 → 修复后

| 反例 | 旧结果 | 当前结果 |
|---|---|---|
| work NOT_APPLICABLE + 通用 threshold | 被重新当作 required | NA、score/threshold 无值、weight=0、不 blocking |
| semantic FAILED + score=100 | 被洗成 PASSED | FAILED 保留；有校准和定位才 LOCAL_REPAIR，否则重新取证 |
| uncalibrated PASSED / PASSED_WITH_UNCALIBRATED + 高分 | 数值阈值洗成正式 PASS | INSUFFICIENT_EVIDENCE、EVIDENCE_REASSESSMENT |
| 未配置必要 numeric measurement | 可能当成足够的 PASS | 明确 measurement 不足、不可借 calibration 标签绕过 |
| work Mission 方法 None | runtime projection 填 hook/reward/曲线/人物魅力/压力 | projection2 精确保留 None/空选择；不能凭公共 profile 复活 |
| 作品选择具体 reward_action | normalize 后 Writer 只剩 applicability | Draft Plan v3 和各阶段 baseline 保留 exact selected_values |
| Book 方法 APPLICABLE + Chapter NA | 章节可逃逸 | QUALITY_APPLICABILITY_CONFLICT |
| 新 3.8 显式选择旧 Style v3 | 丢 Book declaration，转 NA | Writer 前 STYLE_PROJECTION_MIGRATION_REQUIRED |
| context 两任务进入正式 Router | ROUTING_TASK_POLICY_REQUIRED | 合资格受控候选可 SELECTED；冷/失败 cohort 仍拒绝 |
| 同 Effect 多 generation / stale ModelCallLog | 证据行选择可能不确定/洗失败 | native receipt integrity + stable generation、失败历史保留 |

起始 main 的四个 Quality 回归真实失败，见 `nf-qc-baseline-regression-final.log`；Style 门修复前 eef323b 的三个反例均为 NOT_RAISED，见 `nf-qc-style-before-regression.log`。当前对应定向测试通过。保留这些原失败，而非改断言求绿。

## 正式调用链与绑定

```text
Author Input / CreativeBrief Content command
  → exact frozen Formation policy + Author Input + source hashes
  → StoryFormation runtime/Planning generators
  → independent evaluation / bounded repair
  → StoryDesign approval + BookDesign exact six-layer activation
  → creation-input coordinator / explicit runtime policies / genesis
  → Planning Book/Volume/Group + frozen NarrativeRealization + Mission/Scene v3
  → projection2 / Opening / native Book and Chapter worker
  → Plan / ExecutionIntent(selected Style v4) / Memo
  → Context task selection
      overflow → Router context_compress → native Effect/receipt
               → Router context_fidelity → independent Effect/receipt
               → exact source restoration + fidelity recheck / fail closed
  → Draft → Review → bounded Revision(empty edits allowed) → exact ReReview
  → candidate comparison → Quality v2 / aggregate v5 → Canon candidate
  → Book Acceptance atomic candidate/outcome/Canon/state/projection/cursor
  → next unit exact accepted state / native retry or resume
```

当前绑定：Chapter 3.8.0 / author3.8、Pack 2.12.0、System v3、Template v9、prose-generation-v4、quality-review-v3；既有合法 Schema 版本保留。Work Mission v3 / projection2 / activated-chapter-plan.v2、Style compile2.1.4/v4、creative-baseline.v1（含方法 selected_values）、QualityContext v6、work-quality.v2、aggregate v5、Router v12。每个 attempt 继续冻结实际 Pack、Prompt、Skill、Schema、route/model/revision、source、baseline 与 target；successful Effect replay 不重新读取当前 Prompt/容量。采样的执行版本和源语义版本分别绑定。

新作品默认不选择已知污染的旧合同。旧冻结任务可按原身份重放已确认 Effect；不安全的继续生产明确阻断并要求 owning-command 迁移。历史审计及已接纳 v1 连续性仍可读取，不被重算为新策略资格。

## 验证清单

| 检查 | 实际结果 | 证明的能力 |
|---|---|---|
| 七组 Quality/applicability/input/Context/sampler 定向 unit | 164 passed | 旧失败反例、控制权、calibration、版本/来源隔离、精确方法传播 |
| 修复前 Style 三反例 | 3 failed（预期 red） | 回归具备区分力 |
| native Router + dispatch + Book scope + Effect 边界 | 77 passed | strict/failure admission、reservation recovery、跨 Book scope、idempotency、UNKNOWN/measurement settlement |
| 接纳/Group 状态不变量迁移后的原断言 | 5 passed / 88.40s（最终实现复跑） | rollback、并发接纳一次、原子 projection、resume、zero-change lost-response |
| 正式作者三作品 + 两 recovery + overflow + feedback | 15 passed / 474.82s | 正式 production composition 的 MOCK_E2E 与 native feedback denominator |
| 独立复核 | 最终 SHA 的85 passed + STATIC 调用链复核 | 发现并复验 Style override 漏洞；最终无新 P0 |
| manifests / architecture fitness / docs / instruction / test / historical / proposal / head / Ruff ratchet / compile / diff | PASS | 既有仓库边界与身份一致性；不是完整 backend qualification |

没有用字段存在、HTTP 200、解析成功或 mock 预设文案代替状态证明。所有 PG 测试串行使用本包独占数据库；未启动真实生产服务。原 native 矩阵曾为 79PASS/5FAIL，错误的3.4.1 wrapper曾5FAIL并已删除，输入迁移也保留中间 failure。状态 fixture 使用真实编译/投影，但仍手工提供 Foundation、realization、fixture waiver 和 ELIGIBLE 记录，严格标记 OFFLINE，不计入正式作者 E2E。Group 第三章的旧16k、64k授权拒绝均保留；最终状态测试明确196608授权，不修改默认预算或内部 gate。压缩/mandatory overflow 的拒绝与恢复另外测试，不用调大预算冒充压缩成功。

正式 MOCK_E2E 使用真实 ProductionProviderRouter，仅替换 registry.observations 为受控、未落库的测试 cohort，并使用0价格、标记 scripted 的 transport。没有关闭 Router、直接调用 Writer 或把 fixture 观察写成真实 qualification。

## E2E 输入与状态证据

`INPUT_PROPAGATION.json` 是三作品的可核对提取；`mock-e2e-artifacts.zip` 和 `mock-artifact-index.json` 保留完整原始输入、Provider transcript、route snapshots、workspaces、accepted manuscripts 及 hash。

- 严肃现实观察、轻松幻想冒险、克制科幻：各自 genre/audience/tone/structure、人物/世界要求、禁止项及 optional craft 作为作者输入；POV明确第三人称限知，非公共默认。三作品都明确不采用 reward/hook。输入只在测试侧，不进入 Prompt/Skill/default config。
- 每件作品3章、最终 accepted cursor=3；每章选定 candidate 与 committed acceptance 完全一致，Quality 与候选 baseline digest 相同。
- 第二/三章 Context 的 accepted_through_chapter 分别为1/2，其 state/canon snapshot IDs 精确等于前一章 committed 接纳结果，不读取候选状态。
- 观察样例接受原稿，Revision empty edits；其他样例对明确客观缺陷作定位修复，未涉及 slots/文本保留，ReReview/Quality 指向修改后的精确候选。
- 两个额外单章正式 recovery 保留旧 schema failure / evaluation failure、bounded replacement 和原 frozen inputs，再完成接纳；不覆盖失败历史。
- overflow 单例使用隔离项目冻结测试 Pack1.0（普通作者 E2E使用当前正式Pack），保存 source、required units、independent fidelity、native frozen effects、changed-source/fence rejection，并实际继续 Draft/Review。74794→29188 conservative tokens（32768预算），四个 semantic Effects；原始 native请求、Attempt、Dispatch/VERIFIED receipt、ModelCallLog和Context存入 `context-native-snapshot.json.gz`，索引为 `CONTEXT_NATIVE_EVIDENCE.json`。其故意不完整 Quality fixture仍明确被 gate阻断；它不能冒充完整接纳，完整接纳由三作品另行证明。

该传播项证明作者输入进入实际命令/参数、语义资产、版本与持久状态，**不证明 scripted 正文真的符合题材或文风**。接纳的短小模拟文本不是连续文学稿件，人物/世界/POV在真实模型下的写作效果仍待独立验证。

## 独立复核与最终控制权

独立 reviewer 只读复核真实入口、迁移/版本、qualified dimensions、Review veto、辅助分数、bounded edits、native receipt generations、sampler源语义和最终公共投影。其发现的 exact selected_values 丢失、旧污染 projection 再选择、sampler 源语义漂移、旧Style override 逃逸都已修复并加入回归；最终无新增 P0。

当前作品决定 genre、audience、style/tone、POV、长度/结构、角色与世界要求、禁止元素、可选技法与明确不采用的方法；批准后的 typed计划决定具体场景/方法值。公共系统决定格式/身份、存储原子性、证据资格、范围/知识边界、容量/预算/权限/恢复，以及要求已生效时如何测量。新生产投影不能无条件制造商业奖励、悬念钩子、人物成长、升级冲突或结局形态。旧生成资产与受控 Provider 自身的内容不能据此被宣传为文学证明。

## 剩余边界及下一步

本包无已知未修复工程阻断。真实Provider、模型/语义fidelity资格、长篇及文学质量、作者UI实机、部署和自然运行均未验证；完整 backend qualification matrix也未执行。临时实例和测试依赖只服务本包验证，清理凭据/资源身份见交付 manifest。

没有必要为同一已闭合工程目标再建立重复修复包。若要提高证据等级，下一项应是**单独授权并设有限预算的真实 Provider qualification/有限连续稿试验**，以精确 baseline、文本、独立审读和真实 receipts检验效果；不得将本次 MOCK_E2E 当成其替代。本次未请求或调用该授权。
