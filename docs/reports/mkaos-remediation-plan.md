# MKAOS 修复与工业化接入计划

生成时间：2026-07-03

## 1. 当前结论

MKAOS P0 可以视为**有条件完成**：最小闭环、四个核心 Flow Adapter、source isolation、usage、基础 feedback、UI 和测试均成立；但生产级 Novel OS 还不能把它当作完整知识操作系统。

有条件完成的条件：

1. Canon conflict 明确标记为 P1 加固项。
2. Pack 构造失败 warning 降级仅用于 compat/dev/sample，生产路径必须 policy 化。
3. MKAOS 尚未通过统一 Context Builder 提供上下文，不得宣称所有 Agent 已不可绕过。
4. RAG/source leakage 需要专项回归。
5. API envelope、trace、permission、Query/Convert API 仍需后续补齐或明确推迟。

## 2. 必须立即修的问题

| 优先级 | 问题 | 处理方式 | 涉及文件 |
| -- | -- | -- | -- |
| P0_BLOCKER | 无立即阻断当前 P0 审计结论的问题。 | 不建议重做 MKAOS。 | 无 |
| P1_HIGH | Canon conflict validator 能力不足但 API 已暴露。 | 在文档和 UI/API 返回中标明当前为基础检查；Phase 2 接真实 Canon/Character/Arc/Foreshadowing。 | `src/novel_forge/modules/mkaos/service.py`、continuity modules |
| P1_HIGH | MKAOS Pack 构造失败 production fail policy 缺失。 | 并入 OS Envelope/runtime policy，不在四个服务继续散落 try/except。 | 四个 production services、runtime policy |
| P1_HIGH | 缺 MKAOS RAG/source leakage 专项测试。 | 先补测试，不改变业务逻辑。 | `tests/unit/test_mkaos.py` 或新增 integration test |
| P1_HIGH | 当前审计结果需要同步后续工业化设计。 | 更新设计/提示词，防止后续任务误判“全量 MKAOS 已完成”。 | `docs/design/novel-os-v6-industrialization-design.md`、`docs/prompts/claude-code-novel-os-v6-long-task-prompts.md` |

## 3. Post-MKAOS 工业化 Phase 2

Phase 2 目标：不重做 MKAOS P0，把它从“可用 P0 知识模块”加固为“生产链路可治理的知识底座”。

建议纳入 Phase 2：

1. 新增 `recap`、`revision`、`publish`、`feedback` adapter policy。
2. Pack selector 加强：discipline、task_goal、quality_score、risk filter、token estimate。
3. Canon conflict 接入真实 continuity assets。
4. API contract 加强：Query API、Convert API 或明确推迟。
5. Postgres projection 策略决策：扩列或 JSONB 索引。
6. Pack failure policy：compat warning vs production fail-closed。

## 4. 并入 Context Builder 的问题

| 问题 | 目标 |
| -- | -- |
| MKAOS Pack 由四个服务自行构造 | 统一由 Context Builder 根据 task_type 构造/引用 MKAOS Pack。 |
| Pack budget 与 context token budget 分裂 | Context Bundle 同时记录 token budget、knowledge budget、pack warnings。 |
| draft 有 Context Bundle 但 MKAOS Pack 不在 bundle 内 | `ContextBundle.content` 增加正式 `mkaos` 字段。 |
| outline/chapter/review 仍未生成 Context Bundle | 迁移为每个模型调用都带 `context_bundle_id` 与 `knowledge_pack_id`。 |

## 5. 并入 Eval / Review Issue 的问题

1. 将 `validate_artifact` issues 转为统一 `ReviewIssue`。
2. 定义 `issue_type=mkaos_conflict|anti_encyclopedia|knowledge_usage|canon_conflict`。
3. high/critical MKAOS issues 按 blocking policy 阻断 canonical chapter/publish gate。
4. `feedback/review` 不只写 quality score，还能关联 ReviewIssue 和 RevisionTask。
5. Review report 中保留 MKAOS 原始 validation payload，统一 issue asset 负责治理。

## 6. 并入 Loop Engineering 的问题

1. Pack 使用效果进入 loop evidence。
2. 连续低效知识触发 human gate 或 weight update proposal。
3. MKAOS issue 命中后进入 review-rewrite-revalidate loop。
4. LoopRun 记录 `knowledge_pack_id`、`context_bundle_id`、`review_issue_id`。
5. pack build failure 在 loop policy 中决定 retry、fallback、block。

## 7. 并入 Longform Recap Agent 的问题

1. 新增 `recap` flow / pack policy。
2. `recap_context` 必须包含 MKAOS recap pack、Canon、Issue History、FactLedger、Foreshadowing、Arc。
3. Recap Agent 输出对知识有效性的复盘：高价值、低效、冲突、待废弃、可模板化。
4. Recap 只能提出 Canon/Knowledge 更新建议，不直接覆盖项目 Canon。
5. usage events 必须可被 recap 按 project/flow/chapter 查询。

## 8. UI P1/P2

| 阶段 | UI 项 |
| -- | -- |
| UI P1 | Knowledge Pack debugger：选择 project/flow/chapter，显示 selector 分数、预算、被过滤原因。 |
| UI P1 | Knowledge usage map：知识影响了哪些 pack、章节、review issue、revision task。 |
| UI P1 | Quality/weight panel：quality score、weight history、feedback source、是否已应用。 |
| UI P1 | RAG bucket policy panel：显示 MKAOS 运行资产为何不能进 generation RAG。 |
| UI P2 | 知识血缘图：source chunk -> knowledge card -> binding -> pack -> artifact -> feedback。 |
| UI P2 | 版本管理：knowledge/rule/template/card diff 与 rollback。 |
| UI P2 | 批量管理：批量启用/禁用/降权/废弃/绑定 flow。 |

## 9. 推荐 commit 顺序

1. `docs: add mkaos design audit reports`
   - 提交本次四份报告。
2. `docs: mark mkaos p0 conditional completion`
   - 调整工业化设计和长任务提示词，写清 P0 条件和 P1 缺口。
3. `test: add mkaos isolation and api contract regressions`
   - 先补 RAG/source leakage、invalid flow、disabled binding、prose raw_text、empty pack policy 测试。
4. `feat: enforce os envelope for mkaos mutations`
   - 给 MKAOS mutation/build/feedback API 接 envelope/trace/runtime policy。
5. `feat: harden mkaos selector and canon validation`
   - selector scoring、risk filtering、真实 continuity 接入。
6. `feat: route mkaos packs through context builder`
   - Context Bundle schema/task policy 接入 MKAOS。
7. `feat: integrate mkaos issues with review issue loop`
   - ReviewIssue、RevisionTask、Loop evidence。
8. `feat: add recap publish feedback mkaos adapters`
   - 补 Post-MKAOS flow。
9. `feat: expand mkaos console diagnostics`
   - UI P1。

## 10. 推荐测试补充清单

| 测试 | 目标 |
| -- | -- |
| MKAOS source leakage test | Prose pack、prompt-preview、Context Bundle 均不得出现 `source_chunk.raw_text`。 |
| MKAOS RAG isolation test | 手动选择 `knowledge_pack`、`knowledge_usage_event`、`source_chunk`、`agent_run` 时必须被 generation context policy 拒绝。 |
| Query/Convert API tests | 若实现 API，覆盖 happy path 和 missing/invalid flow。 |
| Pack selector tests | discipline/task_goal/quality/risk/budget 对排序和过滤生效。 |
| Canon real integration tests | Canon database、character state、foreshadowing/fact ledger 冲突可阻断。 |
| Pack failure policy tests | compat mode warning；production mode fail-closed。 |
| Feedback loop tests | review feedback -> quality score -> weight update -> next pack selection。 |
| 10 fixture regression suite | 土地兼并、因果链、伏笔、创伤反应、证词矛盾、百科化反例、场景化正例、Canon 冲突、大纲有效调用、细纲有效调用。 |
| UI route/API smoke | `/mkaos`、pack preview、risk list、usage map 后续入口不退化。 |

## 11. 是否需要调整工业化设计文档

需要调整 `docs/design/novel-os-v6-industrialization-design.md`。

建议改动：

1. 把“已完成 MKAOS P0”改为“有条件完成 MKAOS P0”。
2. 明确当前实现满足 P0 最小闭环，但 Query/Convert、Canon real checker、Context Builder 统一入口、OS Envelope、ReviewIssue、RAG isolation regression 未完成。
3. Phase 2 目标改为“生产级加固当前 P0 实现”，不新增重复表。
4. 将本次四份审计报告列为 Phase 0 输出。

## 12. 是否需要调整长任务提示词

需要调整 `docs/prompts/claude-code-novel-os-v6-long-task-prompts.md`。

建议改动：

1. 将“P0 已完成”改为“P0 有条件完成，见审计报告”。
2. 在 Prompt 4 中增加禁止重做现有 P0 表/API/service/UI，同时要求先补测试和 policy。
3. 在 Prompt 5 中明确 MKAOS Pack 必须进入 Context Bundle，四个服务不得长期自行拼接。
4. 在 Prompt 6 中明确 MKAOS validation issue 必须转换为 ReviewIssue。
5. 在 Prompt 11 中加入 MKAOS publish/feedback pack 的前置依赖。

## 13. 是否建议进入 Post-MKAOS 工业化阶段

建议进入，但顺序应调整为：

1. 先合并审计报告和文档修正。
2. 先补测试和 OS Envelope。
3. 再做 MKAOS Phase 2 加固。
4. 再统一 Context Builder。
5. 再推进 ReviewIssue、Loop、Longform Recap、Agent Center 和 UI。

不建议继续开发新的长篇功能前跳过 Context Builder 和 Canon/RAG isolation 加固；那会让 MKAOS 继续以“服务内临时上下文”的形式扩散，增加后续回收成本。
