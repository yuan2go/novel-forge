# Claude Code 长任务提示工程：Novel OS v6.1 Post-MKAOS 工业化补全

> 使用场景：多学科知识资产操作系统（MKAOS）P0 经原始设计审计后为 **有条件完成**，继续驱动 Claude Code 对 Novel OS v6 分支进行工业化补全。  
> 核心要求：不要重复实现 MKAOS；以 `docs/reports/mkaos-*.md` 审计结论为基线，先补 RAG/source leakage、OS Envelope、MKAOS selector/Canon、Context Builder、ReviewIssue，再循环实现 Loop、长篇复盘、Agent Center、UI、发布反馈闭环。

---

## 使用方式建议

不要一次性把所有提示词全部贴给 Claude Code。建议分三轮执行：

```text
第一轮：Prompt 0 + Prompt 1 + Prompt 2
目标：冻结 Post-MKAOS 工程基线，更新设计文档，提交 docs commit。

第二轮：Prompt 3 + Prompt 4 + Prompt 5 + Prompt 6
目标：完成 RAG/source leakage 回归、OS Envelope、MKAOS selector/Canon 加固、Context Builder、ReviewIssue。

第三轮：Prompt 7 + Prompt 8 + Prompt 9 + Prompt 10 + Prompt 11
目标：完成 Loop Engineering、长篇复盘 Agent、Agent Center、UI、发布反馈、最终验收。
```

如果希望 Claude Code 进入目标循环模式，可以直接使用最后的“总长任务提示词”。

---

# Prompt 0：总控提示词，Post-MKAOS 版本

```text
你现在是 novel-forge / Novel OS v6 的工程总控与产品架构实现者。

当前最新基线：
多学科知识资产操作系统（MKAOS）P0 最小闭环已经实现，但原始设计审计结论为有条件完成，总体一致性评分 78/100。不要重复实现 MKAOS。

有条件完成的条件：
- Canon conflict 仍是基础检查；
- warning fallback 仅限 compat/dev/sample；
- MKAOS 尚未统一进入 Context Builder；
- MKAOS 尚未统一进入 OS Envelope；
- MKAOS issue 尚未统一进入 ReviewIssue；
- 必须补 RAG / source leakage 回归测试。

已知完成范围：
- 已实现 M1-M9：模型/schema、migration、来源导入清洗、知识卡、用途绑定、Rule/Template Card、Knowledge Pack Builder、4 个 Flow Adapter、校验 API、反百科化/Canon stub、Usage/Feedback、最小 UI、回归验收。
- 后端核心：src/novel_forge/modules/mkaos/service.py
- API：src/novel_forge/api/routers/mkaos.py
- Migration：src/novel_forge/storage/migrations/versions/v20260702_0003_mkaos_p0.py
- UI：web/admin/app/features/mkaos/MkaosConsolePage.tsx
- 测试：tests/unit/test_mkaos.py
- 新增表：source_documents, source_chunks, knowledge_cards, knowledge_usage_bindings, rule_cards, template_cards, knowledge_packs, knowledge_pack_items, knowledge_usage_events, knowledge_quality_scores。
- 已接入 Outline/ChapterOutline/Prose/Review 服务的 Knowledge Pack。
- Prose pack 强制不包含 source_chunk.raw_text。
- Review 注入 MKAOS 校验 issue，并支持 feedback/weight 回写。
- Pack 构造失败时 warning 降级，不破坏旧流程。
- 已有 RAG bucket 隔离策略、上下文预算、sample pipeline 幂等、项目作用域 lineage 等基础能力，但仍需要 MKAOS 专项回归证明。
- 测试结果：python3 -m unittest discover -s tests -p 'test_*.py' 通过；python3 -m unittest tests.integration.test_pipeline 通过；npm --prefix web/admin test 通过；npm --prefix web/admin run build 通过。

现在目标：
在当前 v6 分支基础上，把 Novel OS 从 early runtime + MKAOS P0 推进到 production-grade longform control layer。

必须完成：
1. 先冻结 MKAOS 审计后的真实基线；
2. 更新详细设计文档和实施计划；
3. 先补 RAG / source leakage 专项回归；
4. 强制完善 OS Envelope；
5. 对 MKAOS selector / Canon conflict 做生产级加固，但不要重做 P0；
6. 完善 Context Builder；
7. 完善 ReviewIssue 阻断系统；
8. 完善 Loop Engineering Kernel；
9. 完成长篇复盘 Agent；
10. 完善 Agent Center；
11. 完善 UI 可编辑控制台；
12. 完善读者反馈与发布闭环；
13. 最后再次完整分析工程现状，输出实现情况、遗留问题、距离工业化 Novel OS 的差距。

硬性约束：
- 不要重写项目，不要另起炉灶。
- 不要重复创建 MKAOS 已有表、API、service、UI、测试。
- 先审计，再设计，再实现，再测试，再提交。
- 所有新增能力必须有 schema / service / tests / docs / reports。
- 所有生产写入路径必须受 OS Envelope 约束。
- 所有模型调用必须通过 Context Builder，具备 context_bundle_id、knowledge_pack_id、trace、cost ledger、provider guard。
- blocking issue 必须阻断 canonical chapter 和 release package。
- Longform Recap Agent 必须能回写 Canon / Character / Foreshadowing / Arc / ReviewIssue / RevisionTask。
- source isolation 和 RAG bucket isolation 不得回退。
- 关键路径不能只做 mock，必须有真实 proof 或可运行 fixture。
- 每完成一个阶段，必须输出 docs/reports/* 报告并 git commit。

请先执行 Prompt 1：Post-MKAOS 当前工程完整审计。不要直接写代码。
```

---

# Prompt 1：Post-MKAOS 当前工程完整审计

```text
请完整分析当前 v6 工程在 MKAOS P0 完成后的真实状态。

必须输出：
1. docs/reports/v6-current-state-after-mkaos.md
2. docs/reports/mkaos-p0-implementation-report.md
3. docs/reports/v6-risk-register-after-mkaos.md
4. docs/reports/v6-industrialization-plan-after-mkaos.md

重点审计范围：

A. MKAOS 当前实现
- src/novel_forge/modules/mkaos/service.py
- src/novel_forge/api/routers/mkaos.py
- src/novel_forge/storage/migrations/versions/v20260702_0003_mkaos_p0.py
- web/admin/app/features/mkaos/MkaosConsolePage.tsx
- tests/unit/test_mkaos.py
- source_documents, source_chunks, knowledge_cards, knowledge_usage_bindings, rule_cards, template_cards, knowledge_packs, knowledge_pack_items, knowledge_usage_events, knowledge_quality_scores

B. MKAOS 已接入链路
- Outline service 是否真实接入 Knowledge Pack
- ChapterOutline service 是否真实接入 Knowledge Pack
- Prose service 是否真实接入 Knowledge Pack
- Review service 是否真实接入 Knowledge Pack
- Prose Pack 是否强制不包含 source_chunk.raw_text
- Review 是否注入 MKAOS 校验 issue
- Usage event 是否写入
- feedback weight update 是否写入

C. 回归修复确认
- RAG bucket 覆盖问题是否已修复
- 上下文预算是否可控
- sample pipeline 二次幂等是否通过
- project scope lineage 是否正确
- MKAOS 运行资产和 Agent runtime 资产是否已从 generation RAG 隔离

D. Novel OS 其他模块现状
- OS Envelope / runtime policy 现状
- Context Builder 现状
- Eval / ReviewIssue / RevisionTask 现状
- Loop Engineering / workflow runtime 现状
- Longform Stability / 长篇复盘相关现状
- Agent Center 现状
- UI 控制台现状
- Publishing / Feedback 现状
- Provider Guard / Cost Ledger / Trace 现状
- Release Package Gate 现状

E. 必须识别的风险
- MKAOS Pack 构造失败 warning 降级是否会污染生产路径
- Canon conflict validator 是否仍是 stub
- source isolation 是否只覆盖 Prose，是否覆盖 prompt preview / publish
- MKAOS 是否受 OS Envelope 管理
- MKAOS usage / feedback 是否有 project scope 和 lineage
- blocking issue 是否能阻断 canonical chapter 和 release package
- 12 章 / 30 章长篇验收是否真实存在

文档要求：
- 每个判断尽量引用具体文件、类、函数、测试、命令。
- 对无法确认的路径标记 unknown，不要假设已经完成。
- 明确列出：已完成、可复用、需加固、需新建、禁止重复实现。
- 最后给出 MKAOS 完成后的最优落地顺序。

完成后运行：
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m unittest tests.integration.test_pipeline
npm --prefix web/admin test
npm --prefix web/admin run build

如果某个命令因环境缺失无法运行，请记录原因，不要伪造结果。
```

---

# Prompt 2：更新设计文档并提交 GitHub

```text
请基于 Prompt 1 的审计结果，更新或新增以下文档：

1. docs/design/novel-os-v6-industrialization-design.md
2. docs/reports/v6-industrialization-plan-after-mkaos.md
3. docs/reports/v6-risk-register-after-mkaos.md
4. docs/reports/mkaos-p0-implementation-report.md

设计文档必须明确：
- 当前 MKAOS P0 为有条件完成，不要重复实现。
- 后续任务从 RAG/source leakage 回归、OS Envelope、MKAOS selector/Canon 加固、Context Builder、ReviewIssue、Loop Engineering、长篇复盘 Agent、Agent Center、UI、发布反馈闭环继续。
- MKAOS 已有表、API、service、UI、测试清单。
- MKAOS 当前风险：Canon stub、warning fallback、source isolation 范围、RAG isolation 回归保护、project scope lineage、OS Envelope 接入。
- 每个后续模块的技术目标、功能设计、功能逻辑、实现细节、测试方案、验收标准。
- GitHub 分支、commit 顺序、最终验收报告路径。

推荐分支：
feat/v6-post-mkaos-industrialization

提交：
git add docs/design/novel-os-v6-industrialization-design.md docs/reports/
git commit -m "docs: update Novel OS industrialization plan after MKAOS P0"

提交前必须检查：
- 不要提交生成缓存。
- 不要覆盖 Claude Code 当前未提交代码。
- 如果存在未提交变更，先输出 git status 并判断是否属于本任务。
```

---

# Prompt 3：RAG / Source Leakage 回归测试

```text
请先补齐 MKAOS 完成后的 RAG / source leakage 专项回归测试。

目标：在后续 Context Builder、Publish、Recap 和 Agent Center 扩展前，证明 `source_chunk.raw_text` 不会进入生成链路，MKAOS runtime asset 不会污染 generation RAG。

必须完成：
1. 审计当前 RAG bucket 隔离逻辑。
2. 审计 prompt preview、chapter prompt、publish pack、recap context 的 raw_text 泄漏路径。
3. 新增回归测试：
   - RAG bucket isolation；
   - source_chunk.raw_text 不进入 Prose pack；
   - source_chunk.raw_text 不进入 prompt preview；
   - source_chunk.raw_text 不进入 chapter prompt；
   - source_chunk.raw_text 不进入 publish pack；
   - source_chunk.raw_text 不进入 recap context；
   - runtime asset 不污染 generation RAG；
   - MKAOS pack budget；
   - project-scoped lineage。
4. 输出 `docs/reports/phase-1-rag-source-leakage-report.md` 和 `docs/reports/rag-isolation-proof.md`。

特别要求：
- 如果当前没有 publish pack 或 recap context，可以建立最小 adapter/test seam，但不要做大功能。
- 不得让 `source_chunk.raw_text` 进入 prose、prompt preview、chapter prompt、publish pack、recap context。

验收标准：
- MKAOS unit test 通过。
- RAG / source leakage 新增测试通过。
- 旧 pipeline 不回归。

提交：
git commit -m "test: add RAG isolation and source leakage regression coverage"
```

---

# Prompt 4：OS Envelope 与 MKAOS 接入

```text
请实现或补全 OS Envelope，并完成 MKAOS 完成后的全路径强制接入审计。

目标：所有 production MKAOS mutation、pack build、usage、feedback 和 production write path 必须受 OS Envelope 约束，不能绕过 Novel OS runtime。

必须完成：
1. 审计已有 OS Envelope / runtime policy / provider guard / cost ledger / trace 实现。
2. 定义或补全 OS Envelope schema。
3. 将 MKAOS source import、knowledge mutation、usage binding、rule/template、pack build、usage event、feedback、weight update 纳入 envelope。
4. production 路径缺 envelope 时 fail closed。
5. dev/sample/test 可显式 bypass，但必须写入 bypass_reason。
6. 增加 Query / Convert API 或 query/convert service，满足原设计扩展接口。
7. 输出 docs/reports/phase-2-os-envelope-mkaos-report.md、docs/design/os-envelope-design.md、docs/reports/os-envelope-enforcement-audit.md。

提交：
git commit -m "feat: standardize OS envelope for MKAOS paths"
```

---

# Prompt 5：MKAOS Selector / Canon Conflict 加固

```text
请对已完成的 MKAOS P0 做生产级集成加固。注意：不要重做 MKAOS，不要重复创建已有表、API、service、UI、测试。

当前已有：
- src/novel_forge/modules/mkaos/service.py
- src/novel_forge/api/routers/mkaos.py
- v20260702_0003_mkaos_p0.py
- web/admin/app/features/mkaos/MkaosConsolePage.tsx
- tests/unit/test_mkaos.py
- Outline/ChapterOutline/Prose/Review Flow Adapter

必须完成：
1. 审计 MKAOS 已有实现，确认不破坏已有 API 和测试。
2. 加固 MKAOS selector：
   - project scope；
   - task_type；
   - usage binding；
   - quality score；
   - feedback weight；
   - risk flag；
   - token budget；
   - recency / version；
   - source policy；
   - priority。
3. 证明 feedback / quality / weight 会影响后续 pack 排序或选择。
4. 将 Canon conflict validator 从兼容基础检查升级为稳定 adapter interface，支持 Canon / Character / Arc / Foreshadowing / WorldRule 输入。
   - 如果真实资产层尚不完整，先实现 adapter interface 和可测试 fixture，不能继续伪装成已完成。
5. 将 canon conflict 输出转成标准 issue candidate，供 ReviewIssue 阶段消费。
6. 输出 docs/reports/phase-3-mkaos-selector-canon-report.md、docs/design/mkaos-selector-and-canon-conflict-design.md、docs/reports/mkaos-feedback-weight-proof.md。

新增测试：
- selector respects feedback weight。
- selector respects project scope。
- selector respects risk exclusion。
- canon conflict returns structured result。
- canon conflict can be converted to review issue candidate。

验收标准：
- 原有 tests/unit/test_mkaos.py 通过。
- python3 -m unittest discover -s tests -p 'test_*.py' 通过。
- python3 -m unittest tests.integration.test_pipeline 通过。

提交：
git commit -m "feat: harden MKAOS selector and canon conflict checks"
```

---

# Prompt 6：Context Builder 统一上下文包

```text
请实现或补全 Context Builder，使所有模型调用前都通过统一上下文包。

目标：任何 Agent 不得自行拼接散乱上下文，必须通过 Context Builder 获取 Context Bundle。MKAOS Knowledge Pack 必须作为 Context Bundle 的正式组成部分。

必须完成：
1. 审计当前 context bundle / context build plan / runtime policy 实现。
2. 定义 Context Bundle 类型：
   - outline_context
   - detail_outline_context
   - chapter_context
   - prose_context
   - review_context
   - revision_context
   - recap_context
   - publish_context
   - feedback_context
3. 为每种 task_type 定义 required assets 和 optional assets。
4. 将 MKAOS Pack Builder 接入 Context Builder，不允许 Agent 自己临时拼 knowledge pack。
5. 缺失 required assets 时必须按 policy fail closed 或 human gate。
6. chapter/prose context 必须包含：前章状态包、Canon、人物状态、Arc、禁改约束、文风样本、MKAOS prose pack。
7. recap_context 必须包含：章节摘要、人物账本、伏笔账本、FactLedger、MotifBudget、VillainOperation、Issue 历史、MKAOS recap pack。
8. publish_context 必须包含：release candidate、blocking issue 状态、longform stability gate、MKAOS publish pack。
9. feedback_context 必须包含：反馈事件、章节映射、Issue 历史、MKAOS feedback pack。
10. 所有模型调用路径必须记录 context_bundle_id 和 knowledge_pack_id。
11. 输出 docs/reports/context-builder-coverage-after-mkaos.md。

上下文预算要求：
- required assets 优先。
- blocking issue 相关资产优先。
- 高权重 knowledge cards 优先。
- source raw text 永远不得进入 prose / publish prompt。
- 超预算时先压缩历史摘要，再裁剪低置信知识。

验收标准：
- 缺失 context_bundle 的模型调用失败。
- outline / chapter_outline / prose / review / revision / recap / publish / feedback 均有 context policy。
- Longform Recap Agent 使用 recap_context。
- make test 或等价测试通过。

提交：
git commit -m "feat: add required context builder policies after MKAOS"
```

---

# Prompt 7：ReviewIssue 系统阻断化

```text
请把现有审稿、gate、MKAOS 校验 issue、longform stability 检查升级为统一结构化 Eval / Review Issue 系统。

目标：所有质量问题必须可定位、可阻断、可回写、可修复。

必须完成：
1. 审计现有 review_issue / revision_task / gate_result / longform stability / MKAOS validation issue 实现。
2. 统一 ReviewIssue schema，至少支持：
   - metadata_leak
   - source_raw_text_leak
   - canon_drift
   - character_drift
   - logic_gap
   - motif_overuse
   - foreshadow_missing
   - foreshadow_forgotten
   - power_scale_break
   - mkaos_conflict
   - platform_violation
   - ai_tone
   - repetition
   - low_quality
   - reader_fatigue
3. 将 MKAOS validate artifact / validate canon-conflict / risks / feedback review 的结果写入统一 ReviewIssue 或 KnowledgeQualityScore。
4. 定义 blocking policy：
   - high/critical metadata leak 阻断 canonical chapter
   - source raw text leak 阻断 canonical chapter 和 release package
   - high/critical canon_drift 阻断 canonical chapter
   - high/critical character_drift 阻断 canonical chapter
   - high/critical logic_gap 阻断 canonical chapter
   - medium+ platform_violation 阻断 release package
   - high/critical ai_tone 阻断 release package
5. blocking issue 自动生成 RevisionTask。
6. canonical chapter 写入前必须检查 blocking issue。
7. release package 生成前必须检查 blocking issue。
8. 输出 docs/reports/eval-review-issue-hardening-report.md。

新增测试：
- MKAOS conflict issue 被转换为 ReviewIssue。
- blocking issue 阻断 canonical chapter。
- blocking issue 阻断 release package。
- high/critical issue 生成 RevisionTask。
- fixed issue 可以重新进入 verify gate。

验收标准：
- 所有质量问题有 asset_id / evidence / severity / blocking / status。
- 旧 review report 不得绕过 ReviewIssue。
- make test 或等价测试通过。

提交：
git commit -m "feat: unify review issues and blocking gates"
```

---

# Prompt 8：Loop Engineering Kernel

```text
请实现或补全 Loop Engineering Kernel，把生成、审稿、修订、复盘、发布变成可循环、可中止、可恢复、可回滚的工程流程。

目标：不是多轮 prompt，而是 production-grade loop runtime。

必须完成：
1. 审计现有 workflow runtime / agent dispatch / scheduler / trace / checkpoint 实现。
2. 定义或补全：
   - LoopRun
   - LoopStep
   - LoopCheckpoint
   - LoopBudget
   - LoopStopCondition
   - DeadLetter
   - ResumeToken
3. 第一批支持 4 个 loop：
   - Chapter Review Loop
   - Chapter Revision Loop
   - Longform Recap Loop
   - Publish Gate Loop
4. 每个 LoopStep 必须记录：
   - OS Envelope
   - context_bundle_id
   - knowledge_pack_id
   - model_call_id
   - review_issue_ids
   - checkpoint_id
   - trace_id
5. 实现预算约束：
   - max steps
   - max model calls
   - max tokens
   - max cost
   - timeout
6. 实现失败策略：
   - fail closed
   - human gate
   - dead-letter
   - resume from checkpoint
7. 输出 docs/reports/loop-engineering-kernel-report.md。

验收测试：
- Chapter Review Loop 无 issue 时通过。
- Chapter Review Loop 有 blocking issue 时生成 RevisionTask。
- Chapter Revision Loop 修复后重新进入 review。
- Longform Recap Loop 可以触发 recap_context。
- Publish Gate Loop 被 blocking issue 阻断。
- 超预算任务进入 dead-letter 或 human gate。
- checkpoint resume 可运行。

提交：
git commit -m "feat: add loop engineering kernel"
```

---

# Prompt 9：长篇复盘 Agent

```text
请实现 Longform Recap Agent。注意：它不是普通总结器，而是 Novel OS 的高级治理 Agent。

目标：每 10 章 / 每卷 / 重大转折后自动复盘长篇稳定性，并把结论结构化回写系统。

必须完成：
1. 审计现有 longform stability first slice、chapter summary、canon、character、foreshadowing、arc、motif、villain、issue 相关实现。
2. 定义或补全 RecapReport schema。
3. 定义触发条件：
   - 每 10 章
   - 每卷结束
   - 主线重大转折
   - 人物重大变化
   - 连续 blocking issue 超过阈值
   - 发布前最终检查
4. Longform Recap Agent 必须通过 Context Builder 获取 recap_context。
5. recap_context 必须包含 MKAOS recap pack。
6. 复盘检查维度：
   - 主线推进
   - 人物状态变化
   - 伏笔新增 / 回收 / 遗忘
   - 世界观设定变化
   - 战力 / 资源变化
   - 反派行动线
   - 母题消耗
   - 节奏与爽点密度
   - 逻辑风险
   - 人设跑偏风险
   - 读者期待兑现
7. 复盘输出必须结构化，不得只有自然语言。
8. 复盘结果必须可回写：
   - Canon
   - Arc
   - Character Ledger
   - Foreshadowing Ledger
   - Fact Ledger
   - Motif Budget
   - Villain Operation
   - ReviewIssue
   - RevisionTask
   - KnowledgeUsageEvent
   - ChiefEditorNotice
9. 输出 docs/reports/longform-recap-agent-report.md。

验收测试：
- 12 章 fixture 可以触发第 10 章复盘。
- 复盘报告包含结构化字段。
- 复盘发现 high/critical issue 后阻断后续 canonical chapter 或进入 human gate。
- 复盘可以生成 RevisionTask。
- 总编 Agent 可以读取复盘报告。

提交：
git commit -m "feat: add longform recap agent writeback flow"
```

---

# Prompt 10：Agent Center 调度与观测

```text
请完善 Agent Center，使其从 first slice 升级为可观察、可调度、可恢复的控制中心。

目标：用户和总编 Agent 可以看到每次生产、审稿、修订、复盘、发布的运行链路。

必须完成：
1. 审计现有 Agent Center / scheduler / workflow runtime / trace UI。
2. 实现或补全 Agent Registry：登记每个 Agent 的能力、输入输出、依赖、权限。
3. 支持 Run Graph：
   - context build
   - knowledge pack build
   - model call
   - gate
   - issue write
   - revision task
   - recap writeback
4. 支持 Gate Timeline。
5. 支持 Budget Burn：token / cost / call count。
6. 支持 Dead-letter Queue。
7. 支持 checkpoint resume。
8. 支持 Chief Editor Inbox：
   - high/critical issue
   - longform recap warning
   - publish risk
   - human gate task
9. 输出 docs/reports/agent-center-hardening-report.md。

验收标准：
- Agent run 可以查到 OS Envelope / Context Bundle / Knowledge Pack / ReviewIssue。
- LoopRun 状态可以查询。
- dead-letter 可以重试或关闭。
- high/critical issue 会进入 Chief Editor Inbox。

提交：
git commit -m "feat: improve agent center observability"
```

---

# Prompt 11：UI 可编辑控制台

```text
请完善 Novel OS UI 控制台。当前 /mkaos 已有最小管理台，后续重点是核心资产可编辑、可审计、可版本化。

目标：从证据看板升级为可操作的 Novel OS 控制台。

优先实现或补全：
P0：
1. Review Issue Center
2. Longform Recap Report Page
3. Agent Center

P1：
4. Canon Console
5. Arc Console
6. Character Console
7. Foreshadowing Console
8. Motif Budget Console
9. Villain Console
10. Publishing / Feedback Console

每个控制台尽量支持：
- 列表
- 详情
- 创建 / 编辑
- 状态变更
- 版本历史
- 引用关系
- 相关 Issue
- 相关 LoopRun
- 审计日志
- 回滚入口

MKAOS UI 后续增强：
- Knowledge Pack 使用影响分析
- KnowledgeQualityScore 趋势
- 高风险知识列表与处理状态
- 与 ReviewIssue 的关联展示
- source isolation 检查结果展示
- RAG bucket policy 展示

输出 docs/reports/ui-control-console-report.md。

验收标准：
- npm --prefix web/admin test 通过。
- npm --prefix web/admin run build 通过。
- 至少 P0 三个页面可访问。
- /mkaos route 不回退。
- 页面能展示真实或 fixture 数据，不要只有静态假页面。

提交：
git commit -m "feat: add editable Novel OS control consoles"
```

---

# Prompt 12：发布、反馈闭环与最终验收

```text
请完善 Publishing / Feedback 闭环，并进行最终工业化验收。

目标：Novel OS 不只生产章节，还能发布前门禁、生成发布包、接收读者反馈、回写系统并影响后续生产。

必须完成：
1. 审计现有 publishing plan / feedback backflow / release package / platform adapter。
2. Release Package 生成前必须检查：
   - OS Envelope
   - Context Bundle
   - ReviewIssue blocking 状态
   - Longform Stability Gate
   - MKAOS publish pack
   - 平台规则
   - AI 味 / 重复 / 水文
   - 章节排版
   - 书名 / 简介 / 标签 / 封面元数据
3. 定义或补全 FeedbackEvent。
4. 支持反馈聚类：
   - rhythm
   - character
   - logic
   - style
   - hook
   - platform_fit
   - ai_tone
5. 支持反馈回写：
   - ReviewIssue
   - RevisionTask
   - KnowledgeQualityScore
   - KnowledgeUsageBinding weight
   - RuleCard score
   - TemplateCard score
   - ChiefEditorNotice
6. 支持 rollback rehearsal。
7. 输出最终报告：
   - docs/reports/v6-current-state-after-industrialization.md
   - docs/reports/v6-industrialization-gap-report.md
   - docs/reports/v6-acceptance-test-report.md
   - docs/reports/v6-provider-hard-stop-proof.md
   - docs/reports/v6-rollback-rehearsal-report.md

最终验收必须运行：
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m unittest tests.integration.test_pipeline
npm --prefix web/admin test
npm --prefix web/admin run build

如果存在项目已有 make/test 命令，也必须运行。

必须新增或补全验收 fixture：
- 12 章长篇链路
- 第 10 章自动复盘
- blocking issue 阻断 canonical chapter
- revision loop 修复
- release package gate 阻断
- feedback backflow 更新 issue 或 weight
- source isolation regression
- RAG bucket isolation regression
- provider hard-stop proof

最终输出成熟度评分：
- OS Envelope 覆盖
- MKAOS 集成深度
- Context Builder 覆盖
- Eval / Issue 阻断能力
- Loop Engineering 可恢复性
- 长篇复盘回写能力
- UI 控制台可维护性
- 发布反馈闭环
- Provider / Cost / Ops 可靠性

提交：
git commit -m "feat: add publishing feedback loop and acceptance reports"

最后输出：
- git status
- git log --oneline -n 15
- 本分支距离工业化 Novel OS 的剩余 P0/P1/P2 问题
```

---

# 一次性长任务总提示词

```text
你是 novel-forge / Novel OS v6 的工程总控。请在当前 v6 分支基础上，以目标循环模式完成 MKAOS P0 之后的 Novel OS 工业化补全。

当前事实：
多学科知识资产操作系统（MKAOS）P0 最小闭环已经实现，但原始设计审计结论为有条件完成，总体一致性评分 78/100。不要重复实现 MKAOS。你必须把它作为有条件完成的底座进行加固和接入。

有条件完成条件：
- Canon conflict 仍是基础检查；
- warning fallback 仅限 compat/dev/sample；
- MKAOS 尚未统一进入 Context Builder；
- MKAOS 尚未统一进入 OS Envelope；
- MKAOS issue 尚未统一进入 ReviewIssue；
- 必须补 RAG / source leakage 回归测试。

已知完成内容：
- M1-M9 已完成：模型/schema、migration、来源导入清洗、知识卡、用途绑定、Rule/Template Card、Knowledge Pack Builder、4 个 Flow Adapter、校验 API、反百科化/Canon stub、Usage/Feedback、最小 UI、回归验收。
- 后端核心：src/novel_forge/modules/mkaos/service.py
- API：src/novel_forge/api/routers/mkaos.py
- Migration：src/novel_forge/storage/migrations/versions/v20260702_0003_mkaos_p0.py
- UI：web/admin/app/features/mkaos/MkaosConsolePage.tsx
- 测试：tests/unit/test_mkaos.py
- 新增表：source_documents, source_chunks, knowledge_cards, knowledge_usage_bindings, rule_cards, template_cards, knowledge_packs, knowledge_pack_items, knowledge_usage_events, knowledge_quality_scores。
- API：/api/mkaos/sources*, /api/mkaos/knowledge*, /api/mkaos/usage-bindings*, /api/mkaos/rules, /api/mkaos/templates, /api/mkaos/packs/build, /api/mkaos/packs/{id}, /prompt-preview, /api/mkaos/validate/artifact, /validate/canon-conflict, /api/mkaos/usage-events, /api/mkaos/feedback/review, /feedback/apply-weight-update, /api/mkaos/risks, /api/mkaos/acceptance/minimal。
- Outline/ChapterOutline/Prose/Review 服务已接入 Knowledge Pack。
- Prose pack 强制不包含 source_chunk.raw_text。
- Review 注入 MKAOS 校验 issue，并支持 feedback/weight 回写。
- Pack 构造失败时 warning 降级，不破坏旧流程。
- MKAOS 运行资产和 Agent runtime 资产已有 generation RAG 隔离策略，但需要专项回归测试证明。
- 已跑通土地兼并样例。
- 当前测试已通过：python3 -m unittest discover -s tests -p 'test_*.py'；python3 -m unittest tests.integration.test_pipeline；npm --prefix web/admin test；npm --prefix web/admin run build。

目标分支：
feat/v6-post-mkaos-industrialization

执行顺序：
Phase 0：文档基线修正
Phase 1：RAG/source leakage 回归测试
Phase 2：OS Envelope 标准化与 MKAOS 接入
Phase 3：MKAOS selector / Canon conflict 加固
Phase 4：Context Builder 统一入口
Phase 5：ReviewIssue 阻断系统
Phase 6：Loop Engineering Kernel
Phase 7：Longform Recap Agent
Phase 8：Agent Center
Phase 9：UI 可编辑控制台
Phase 10：Publish / Feedback 闭环
Phase 11：12 章压力测试与 Provider hard-stop proof
Phase 12：最终复盘与工业化差距报告

强制要求：
1. 每个 Phase 开始前先审计现有实现，不要盲目新增。
2. 每个 Phase 输出 docs/reports/* 报告。
3. 每个 Phase 有测试和验收命令。
4. 每个 Phase 完成后 git commit。
5. 不要重复实现 MKAOS 已有模块。
6. 所有生产写入必须受 OS Envelope 约束。
7. 所有模型调用必须经过 Context Builder。
8. 所有模型调用必须记录 context_bundle_id、knowledge_pack_id、trace_id、cost ledger、provider guard。
9. blocking issue 必须阻断 canonical chapter 和 release package。
10. source isolation 和 RAG isolation 不得回退。
11. Pack 构造失败 warning 降级只允许 dev/sample/compat，不允许 production canonical chapter/release package。
12. Longform Recap Agent 必须结构化输出并回写 Canon / Character / Foreshadowing / Arc / ReviewIssue / RevisionTask。
13. UI 不要只做静态页面，必须能展示真实或 fixture 数据。
14. 关键路径不能只做 mock，必须有真实 proof 或可运行 fixture。

现在开始执行 Phase 0。先输出 git status，再基于四份 MKAOS 审计报告修正文档基线，不要在 Phase 0 修改业务代码。
```
