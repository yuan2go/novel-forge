# .claude Skills Audit Report

日期：2026-07-05

## 1. 审计范围

本报告基于当前项目 `.claude/skills/` 目录做分析，并记录本次按 root `skills/` source-of-truth 同步后的状态。Skill 内容只在根 `skills/` 新增/更新，runtime copy 通过 `make sync-skills` 生成。

已检查：

- `.claude/skills/*/SKILL.md`
- `.claude/skills/*/LICENSE.txt`
- `.claude/skills/*/scripts/*`
- `.claude/skills/*/reference/*`
- `docs/09-skills/agent-skill-map.md`
- `docs/09-skills/usage-policy.md`
- `scripts/sync_claude_skills.py`
- `Makefile` 中的 Skill 同步命令

验证命令：

- `find .claude/skills -maxdepth 1 -mindepth 1 -type d`
- `wc -l .claude/skills/*/SKILL.md`
- `find .claude/skills -mindepth 2 -type f`
- `make check-skills`

当前 `.claude/skills` 共 38 个 Skill：

- 项目 / Novel OS Skill：29 个
- runtime/vendor 工具型 Skill：9 个

`SKILL.md` 合计约 5,176 行。工具型 Skill 中存在 Python 脚本、Office/PDF 处理脚本、Playwright 测试辅助、MCP eval 脚本和大量 Claude API reference 文档。

## 2. 总体结论

当前 `.claude/skills` 已经从早期小说生产 Skill 集合，扩展为 Novel Forge / Novel OS 的完整能力层：

- 小说生产主链覆盖 Topic、World、Character、Outline、ChapterPlan、Draft、Review、Feedback、Training。
- MKAOS / 分析链覆盖 hot novel、business deconstruction、published fiction、classic literature、anti-copy、analysis-to-asset、knowledge asset、material curation。
- OS 治理链覆盖 Context Builder、ReviewIssue Gate、Agent Loop、Provider Runtime、Canon Continuity、Publish Release Gate、Platform Strategy、Engineering Audit。
- 工具链覆盖 Claude API、MCP、Web UI testing、frontend design、doc coauthoring、PDF/DOCX/XLSX、Skill creation。

本次整改已修复 runtime drift：

- 根 `skills/` 是 source of truth。
- `.claude/skills/` 是 runtime copy。
- 新增 `provider-runtime-policy`、`canon-continuity-graph`、`publish-release-gate-os` 三个根 Skill。
- 新增 `narrative-beat-design`、`skill-governance` 两个根 Skill。
- `chapter-outline`、`long-outline` 已吸收 reader grounding / beat path 方法。
- `project-planning` 已吸收文件结构、接口依赖、测试命令、回滚建议等工程计划格式。
- `writing-fragments`、`writing-shape` 保持外部个人写作 Skill，不进入项目源 Skill。
- 已执行 `make sync-skills-dry-run`、`make sync-skills`、`make check-skills`。
- `make check-skills` 当前通过；项目 Skill runtime copy 与根 `skills/` 一致。

结论：不建议立即删除任何 Skill；应继续对 runtime/vendor Skill 维持限域触发、许可证记录和显式 opt-in。

## 3. Skill 清单、用途与适配度

| Skill | 类型 | 用途 | 适配度 | 风险 | 建议 |
|---|---|---|---|---|---|
| `agent-loop-governance` | Novel OS / Agent | AgentRun、LoopRun、预算、checkpoint、dead-letter、rollback、gate 覆盖 | 高 | 中 | 保留，Agent Center / Loop Kernel 主力 Skill |
| `analysis-to-asset-conversion` | MKAOS / 分析转资产 | 将分析报告转为 schema-backed creative assets，并记录禁用项 | 高 | 中 | 保留，连接分析和生产资产 |
| `anti-copy-abstraction` | 原创边界 | 把具体参考拆解降为不可复原的抽象机制 | 高 | 中 | 保留；已同步 Novel OS Runtime Contract |
| `chapter-outline` | 小说主链 | 章节细纲、冲突、信息增量、爽点、钩子、承接 | 高 | 中 | 保留；已同步 Novel OS Runtime Contract |
| `character-design` | 小说主链 | 人物目标、欲望、恐惧、关系、成长弧和主线功能 | 高 | 中 | 保留；已同步 Novel OS Runtime Contract |
| `classic-literary-depth-analysis` | 文学分析 / MKAOS | 名著主题系统、社会压力、象征、命运曲线抽象分析 | 高 | 中 | 保留，适合深度 craft 资产 |
| `context-builder-source-isolation` | Novel OS / Context | ContextBundle、KnowledgePack、source isolation、token budget | 高 | 高 | 保留，生产链路关键 gate |
| `hot-novel-business-deconstruction` | 商业拆解 / MKAOS | 网文商业结构、平台节奏、读者承诺、hook/payoff loop | 高 | 中 | 保留，优先用于 schema-backed 生产分析 |
| `hot-novel-deconstruction` | 拆解 / 原创边界 | 热门小说结构、节奏、爽点、人物机制抽象拆解 | 高 | 中 | 保留；与 business 版重叠，已同步 contract |
| `long-outline` | 小说主链 | 全书/卷纲/长期连载弧线、伏笔和回收 | 高 | 中 | 保留；已同步 Novel OS Runtime Contract |
| `material-curation` | 素材治理 | 素材生命周期、标签、可生成/只参考/禁用边界 | 高 | 中 | 保留；已同步 Novel OS Runtime Contract |
| `mkaos-knowledge-asset-os` | MKAOS / 知识资产 OS | KnowledgeCard、RuleCard、TemplateCard、Relation、Pack、Selector、Learning | 高 | 高 | 保留，MKAOS 主 Skill |
| `multidisciplinary-knowledge` | 专业知识转译 | 专业知识转为故事可信度、冲突、约束、审稿检查 | 高 | 中 | 保留；生产场景应搭配 MKAOS |
| `narrative-beat-design` | 小说主链 / Beat 设计 | 读者 grounding、beat 顺序、hook/payoff path、信息前置和因果可达性 | 高 | 中 | 保留，配合 `long-outline` / `chapter-outline` |
| `novel-os-engineering-audit` | 工程审计 | 对照 docs/code/tests/UI/gates 输出证据矩阵和修复计划 | 高 | 低 | 保留，适合阶段审计和完成度判断 |
| `platform-strategy-os` | 平台策略 | 起点/番茄/飞卢/晋江/知乎盐选等平台节奏、gate、feedback backflow | 高 | 中 | 保留，平台适配和发布 gate 关键能力 |
| `project-planning` | 规划 | P0/P1/P2、任务池、文件结构、接口依赖、测试命令、回滚建议 | 高 | 中 | 保留；已吸收工程计划格式 |
| `prose-generation` | 小说主链 / Draft | 基于已批准 ChapterPlan 生成正文候选和自检 | 高 | 高 | 保留；必须接 Context/Review |
| `provider-runtime-policy` | Novel OS / Provider | provider hard-stop、fallback approval、timeout、token/cost、model_call_log、cost_ledger | 高 | 高 | 保留，模型调用和成本边界关键 Skill |
| `publish-release-gate-os` | Novel OS / Publish | ReleasePackage、PublishGateReport、平台发布检查、rollback/resume | 高 | 高 | 保留，发布闭环关键 Skill |
| `published-fiction-craft-analysis` | 出版小说技法分析 | 场景经营、叙事距离、角色弧、潜台词、技法参数 | 高 | 中 | 保留，不能模仿作者 |
| `quality-review` | 审稿 / QA | 原创风险、逻辑、节奏、钩子、商业弱点和修订建议 | 高 | 中 | 保留；已同步 Novel OS Runtime Contract |
| `reader-feedback` | 反馈回流 | 评论聚类、采纳/延后/拒绝、后续章节约束 | 高 | 中 | 保留；已同步 Novel OS Runtime Contract |
| `review-issue-gate` | Novel OS / Gate | 将风险和审稿发现结构化为 ReviewIssue、GateResult、RevisionTask | 高 | 高 | 保留，阻断发布和 canonical 化的关键 Skill |
| `skill-governance` | Novel OS / Skill 治理 | Skill 触发边界、single source of truth、progressive disclosure、vendor/license/sync 决策 | 高 | 中 | 保留，Skill 变更和外部吸收必须使用 |
| `topic-development` | 小说主链 | 题材定位、premise、差异化、平台 fit、原创风险边界 | 高 | 中 | 保留；已同步 Novel OS Runtime Contract |
| `training-exercise` | 训练题 | 写作/阅读/翻译/批改训练题和 rubric | 中 | 中 | 保留，非主链但有训练价值 |
| `worldbuilding` | 小说主链 | 世界规则、资源、阶层、组织、代价、冲突钩子 | 高 | 中 | 保留；已同步 Novel OS Runtime Contract |
| `canon-continuity-graph` | Novel OS / Canon | Canon Graph、continuity fact、impact report、invalidation、rollback evidence | 高 | 高 | 保留，正典连续性和冲突阻断关键 Skill |
| `claude-api` | runtime/vendor / API | Claude API、Anthropic SDK、Managed Agents、tool use、token、model migration | 中 | 高 | 限域保留；仅用于 Claude/Anthropic provider |
| `doc-coauthoring` | runtime/vendor / 文档 | 长文档、RFC、proposal、reader testing 协作流程 | 中 | 中 | 限域保留；正式 docs 仍需代码一致性检查 |
| `docx` | runtime/vendor / Office | DOCX 读写、修订、批注、转换、验证 | 中 | 高 | 按需保留；专有许可，依赖 LibreOffice/npm/pandoc |
| `frontend-design` | runtime/vendor / UI | UI 视觉设计、排版、文案和设计自检 | 中 | 中 | 按需保留；需服从本项目前端约束 |
| `mcp-builder` | runtime/vendor / MCP | MCP server 设计、SDK、tool schema、eval | 高 | 中 | 保留；联网和外部 API 需 opt-in |
| `pdf` | runtime/vendor / PDF | PDF 读取、表格、表单、OCR、合并拆分、生成 | 中 | 高 | 按需保留；专有许可，处理来源文本需隔离 |
| `skill-creator` | runtime/vendor / Skill governance | 创建、优化、评测、打包 Skill | 高 | 中 | 保留；只在 Skill 开发任务触发 |
| `webapp-testing` | runtime/vendor / UI 测试 | Playwright、本地服务生命周期、截图、DOM/console 检查 | 高 | 中 | 保留，UI smoke 关键工具 |
| `xlsx` | runtime/vendor / Spreadsheet | XLSX/CSV/TSV 读写、公式、格式、重算和验证 | 中 | 高 | 按需保留；专有许可，依赖 LibreOffice/pandas/openpyxl |

## 4. 用途分组

### 4.1 小说生产主链

- `topic-development`
- `worldbuilding`
- `character-design`
- `narrative-beat-design`
- `long-outline`
- `chapter-outline`
- `prose-generation`
- `quality-review`
- `reader-feedback`
- `training-exercise`

这些 Skill 与 Novel Forge 的 TopicSeed、WorldBible、CharacterCard、Outline、ChapterPlan、DraftChapter、ReviewReport、FeedbackInsight 链路匹配。`narrative-beat-design` 作为大纲和细纲之间的 grounding / beat path 方法层，不替代 `long-outline` 或 `chapter-outline`。当前 runtime copy 已从根 `skills/` 同步，包含统一 Novel OS Runtime Contract。

### 4.2 MKAOS / 分析 / 知识资产

- `hot-novel-deconstruction`
- `hot-novel-business-deconstruction`
- `published-fiction-craft-analysis`
- `classic-literary-depth-analysis`
- `anti-copy-abstraction`
- `analysis-to-asset-conversion`
- `multidisciplinary-knowledge`
- `material-curation`
- `mkaos-knowledge-asset-os`

这组 Skill 覆盖 Source -> Analysis -> Abstract Asset -> KnowledgePack -> Context 的前半链路。生产路径应优先使用带 schema-backed 输出要求的新版分析 Skill，再由 `analysis-to-asset-conversion` 和 `mkaos-knowledge-asset-os` 进入知识资产。

### 4.3 Novel OS 工程治理

- `context-builder-source-isolation`
- `review-issue-gate`
- `agent-loop-governance`
- `provider-runtime-policy`
- `canon-continuity-graph`
- `publish-release-gate-os`
- `platform-strategy-os`
- `novel-os-engineering-audit`
- `project-planning`
- `skill-governance`

这组 Skill 已覆盖上一版报告建议新增的核心治理方向，并补齐 provider hard-stop、canon continuity、publish release gate 和 Skill source-of-truth governance。它们是当前 Skill 集合里最贴近 Agent runtime、Context Builder、ReviewIssue、Loop Kernel、Publish Gate、Platform Feedback Backflow、Skill runtime sync 和 acceptance evidence 的部分。

### 4.4 Runtime / Vendor 工具型 Skill

- `claude-api`
- `mcp-builder`
- `webapp-testing`
- `frontend-design`
- `doc-coauthoring`
- `skill-creator`
- `pdf`
- `docx`
- `xlsx`

这些 Skill 对工程和文件处理很有价值，但不是 Novel OS 生产资产的 source of truth。它们应保留在 runtime/tool 层，只有任务明确需要时触发。

## 5. 重复项与重叠分析

| 重叠组 | 涉及 Skill | 判断 | 建议 |
|---|---|---|---|
| 网文拆解 | `hot-novel-deconstruction`, `hot-novel-business-deconstruction` | 高重叠。前者是人工/Markdown 拆解流，后者更偏 schema-backed 商业分析。 | 保留两者；生产链优先 `hot-novel-business-deconstruction`，旧版作为 operator analysis。 |
| 出版/经典分析 | `published-fiction-craft-analysis`, `classic-literary-depth-analysis` | 中重叠。前者偏技法参数，后者偏主题/象征/社会压力。 | 保留；同一来源不可把两个报告直接塞进 generation RAG。 |
| 知识转译 | `multidisciplinary-knowledge`, `mkaos-knowledge-asset-os` | 连续链路，不是删除型重复。 | `multidisciplinary-knowledge` 做知识转译，`mkaos-knowledge-asset-os` 做资产、gate、selector、learning。 |
| 素材/资产转换 | `material-curation`, `analysis-to-asset-conversion` | 部分重叠。前者偏素材分类和标签，后者偏分析报告转资产。 | 保留；转换生成资产时优先 `analysis-to-asset-conversion`。 |
| 规划/审计/文档 | `project-planning`, `novel-os-engineering-audit`, `doc-coauthoring` | 目标不同。规划拆任务，审计验实现，coauthoring 写长文档。 | 保留；工程真实性判断优先 `novel-os-engineering-audit`。 |
| 审稿/阻断 | `quality-review`, `review-issue-gate` | 连续链路。Review 发现问题，Gate 结构化和阻断。 | 保留；禁止只在 Markdown 报告里保留 blocking issue。 |
| Context / MKAOS | `context-builder-source-isolation`, `mkaos-knowledge-asset-os` | 职责接近但边界清楚。 | MKAOS 管知识生命周期，Context Builder 管生产上下文选择和隔离。 |
| Narrative beat / outline | `narrative-beat-design`, `long-outline`, `chapter-outline` | 连续链路。Beat Skill 管 grounding 与 beat 可达性，Outline Skill 管资产输出。 | 保留；`narrative-beat-design` 不单独完成 production outline，必须回写 Outline / ChapterPlan。 |
| Provider runtime | `provider-runtime-policy`, `agent-loop-governance`, `novel-os-engineering-audit` | 部分重叠。provider skill 管模型调用边界，agent loop 管运行状态，audit 管证据矩阵。 | 保留；生产 provider failure 必须进入 hard-stop 或 approved fallback。 |
| Canon / Publish | `canon-continuity-graph`, `publish-release-gate-os`, `review-issue-gate` | 连续链路。Canon 识别事实冲突，ReviewIssue 阻断，Publish Gate 判定 release readiness。 | 保留；发布不得绕过 continuity 和 blocking issue。 |
| Skill 治理 / 外部吸收 | `skill-governance`, `project-planning`, `skill-creator`, `docs/09-skills/usage-policy.md` | 层级不同。`skill-governance` 是项目治理 Skill，`skill-creator` 是 runtime authoring 工具，usage-policy 是长期规则。 | Skill 变更先用 `skill-governance`；不直接 vendor 外部个人 Skill。 |
| UI 设计与验证 | `frontend-design`, `webapp-testing` | 不重复。一个设计，一个验证。 | 保留；UI 变更后优先搭配本地 smoke。 |
| Office 文档处理 | `pdf`, `docx`, `xlsx` | 格式不同，不重复。 | 保留；只在文件任务触发。 |
| Agent/API/MCP/Skill | `claude-api`, `mcp-builder`, `skill-creator`, `agent-loop-governance` | 易混淆但层级不同。 | Claude provider、MCP server、Skill authoring、Novel OS Agent loop 要分开触发。 |

## 6. 风险项

| 风险项 | 严重级别 | 涉及 Skill | 证据 / 说明 | 建议控制 |
|---|---|---|---|---|
| Runtime drift | 低 | root project Skills | 本次已执行 `make sync-skills`，`make check-skills` 当前通过。 | 继续禁止手工编辑 `.claude/skills`；Skill 变更后必须 dry-run、sync、check。 |
| 生产资产 contract 缺口 | 中 | 创作主链 Skill | runtime copy 已包含 Novel OS Runtime Contract，但 Markdown operator handoff 仍可能被误解为生产完成。 | 生产链必须搭配 `context-builder-source-isolation`、`review-issue-gate`、schema validation 和 gate result。 |
| Provider 路由偏置 | 高 | `claude-api` | 触发条件对 provider 未声明的 LLM 任务很强，可能覆盖 OpenAI/Codex 或 provider-neutral 任务。 | 仅在明确 Anthropic/Claude provider 时使用；OpenAI/Codex 任务走对应项目指令和官方文档。 |
| Provider hard-stop 缺口 | 高 | `provider-runtime-policy`, Agent runtime | 若生产调用不记录 failure、fallback、cost 或 token，会破坏 OS acceptance。 | 新 provider skill 已加入；后续实现必须以 model_call_log / cost_ledger / GateResult 验收。 |
| Canon / publish 闭环缺口 | 高 | `canon-continuity-graph`, `publish-release-gate-os` | 正典变更和发布决策若只靠文本审稿，无法证明 invalidation/resume。 | 新 Skill 已加入；后续实现需绑定 schema、ReviewIssue 和 publish gate 测试。 |
| 专有许可 / 不宜再分发 | 高 | `docx`, `pdf`, `xlsx` | LICENSE 禁止在服务外抽取、复制、派生或分发材料。 | 仅 runtime 使用；不要 vendor 到根 `skills/` 或公开包；提交前需法律/许可证评审。 |
| 外部联网 / 最新文档依赖 | 中 | `claude-api`, `mcp-builder`, `doc-coauthoring` | `claude-api` 和 `mcp-builder` 明确建议 WebFetch / 官方在线文档。 | 默认本地只读；联网必须任务需要或用户明确同意。 |
| Subprocess / server / browser | 中 | `webapp-testing`, `skill-creator`, `docx`, `xlsx`, `pdf` | 存在 Playwright、server helper、LibreOffice、eval viewer、Office/PDF scripts。 | 只在明确任务运行；启动服务后必须收尾；不要纳入默认验证路径。 |
| Context 污染 | 中 | `claude-api`, `docx`, `xlsx`, `skill-creator` | `claude-api` 920K，`docx`/`xlsx` 各 1.2M，`skill-creator` 248K。 | 遵守 progressive disclosure，只读相关 reference，不把大文档整体塞入上下文。 |
| 参考作品泄漏 | 高 | 所有分析、素材、正文相关 Skill | 热门小说/出版小说/专业资料可能被误转为生成素材。 | 必须经过 `anti-copy-abstraction`、MKAOS source isolation、ReviewIssue Gate。 |
| API key / credential 示例 | 中 | `claude-api`, `mcp-builder` | 文档包含 token、OAuth、API key、WIF 等示例。 | 禁止写入真实密钥；日志和报告只记录配置边界，不记录 secret。 |
| 工具 Skill 权限误解 | 中 | runtime/vendor Skill | 工具型 Skill 不等于项目 Agent 权限。 | Skill 不扩权；仍受 AGENTS.md、Runtime Policy、OS Envelope、tests 约束。 |
| 外部个人写作 Skill 误入项目源 | 中 | `writing-beats`, `writing-great-skills`, `writing-plans`, `writing-fragments`, `writing-shape` | 这些位于个人 Skill runtime，不是项目 source of truth；直接 vendor 会带来许可证、触发边界和职责污染。 | 只吸收方法并改写为项目 Skill；`writing-fragments`、`writing-shape` 暂不进入项目源。 |

## 7. 保留建议

必须保留：

- `context-builder-source-isolation`
- `review-issue-gate`
- `agent-loop-governance`
- `mkaos-knowledge-asset-os`
- `analysis-to-asset-conversion`
- `anti-copy-abstraction`
- `quality-review`
- `prose-generation`
- `chapter-outline`
- `narrative-beat-design`
- `long-outline`
- `topic-development`
- `worldbuilding`
- `character-design`
- `platform-strategy-os`
- `provider-runtime-policy`
- `canon-continuity-graph`
- `publish-release-gate-os`
- `novel-os-engineering-audit`
- `project-planning`
- `skill-governance`
- `webapp-testing`
- `mcp-builder`
- `skill-creator`

保留理由：这些直接支撑 Novel OS 的本地优先生产链、MKAOS 知识治理、Agent loop、provider hard-stop、canon continuity、publish release gate、ReviewIssue 阻断、narrative grounding、Skill governance、工程审计和 UI 验证。

建议保留但限域触发：

- `claude-api`：仅 Claude/Anthropic provider、Claude SDK、Managed Agents 或 Claude API migration 任务使用。
- `docx` / `pdf` / `xlsx`：仅文件处理任务使用，且不得把受保护来源文本进入生产上下文。
- `frontend-design`：仅 UI 设计/重构任务使用，仍需遵守本项目 Web Admin 的实用工作台风格。
- `doc-coauthoring`：仅 RFC、PRD、proposal、长文档共创使用。
- `training-exercise`：保留为训练题和能力评测扩展。
- `hot-novel-deconstruction`：保留为旧式/operator 拆解入口，生产路径优先使用 schema-backed 新分析 Skill。

## 8. 删除建议

当前不建议立即删除任何 Skill。

可选删除或停用条件：

| 候选 | 条件 | 影响 | 建议 |
|---|---|---|---|
| `doc-coauthoring` | 长期不做协作文档、RFC、PRD | 减少一个文档流程，但损失 reader testing 方法 | 不急删，低风险保留 |
| `frontend-design` | Web Admin 不再做视觉/交互改造 | 减少一个设计指导 Skill | 保留更划算 |
| `docx` | 不处理 Word deliverable，且专有许可不可接受 | 减少 runtime 体积和许可风险 | 若删除，先记录替代方案 |
| `pdf` | 不处理 PDF 输入/输出，且专有许可不可接受 | 损失 PDF 表格/表单/OCR 能力 | 项目资料导入仍可能需要，谨慎 |
| `xlsx` | 不处理表格/CSV/XLSX deliverable，且专有许可不可接受 | 损失表格清洗和公式验证能力 | 非主链，可条件删除 |
| `claude-api` | 项目明确禁用 Anthropic provider | 减少 provider 偏置和大上下文风险 | 若禁用 Claude，可删除或移出 runtime |
| `hot-novel-deconstruction` | 完全迁移到 `hot-novel-business-deconstruction` | 减少旧式 Markdown 拆解入口 | 先确认所有工作流迁移完成 |

删除或 prune 规则：

- 不要手工删除 `.claude/skills` 作为事实源。
- 根 `skills/` 是 source of truth。
- runtime-only vendor Skill 若要删除，需先确认它不是本地 Claude Code runtime 所需能力。
- 若需要清理，先运行 `make sync-skills-dry-run`，再决定是否带 `--prune` 使用同步脚本。

## 9. 新增建议

上一版报告建议的 MKAOS、Context Builder、ReviewIssue、Agent Loop、Platform Strategy、Engineering Audit 已经存在。近期已新增 Provider Runtime、Canon Continuity、Publish Release Gate、Narrative Beat Design 和 Skill Governance。后续新增建议应更细，面向剩余缺口：

| 建议 Skill | 用途 | 触发场景 | 优先级 |
|---|---|---|---|
| `evaluation-benchmark-os` | 质量、成本、延迟、回归、模型评估 benchmark 的 schema-backed 运行 | Model Evaluation Agent、provider comparison、regression suite | P1 |
| `source-ingestion-rights-gate` | 导入来源的 license、rights、robots、source policy、evidence span gate | 专业书、GitHub、论坛、平台资料、外部数据导入 | P1 |
| `editor-chief-console-eval` | 总编控制台健康度、next-10-chapter strategy、risk heat、release readiness | Editor-in-Chief Console、质量总览、下一阶段策略 | P2 |

## 10. 具体整改建议

1. 保持 runtime drift 修复状态：
   - 本次 `make check-skills` 已通过；
   - 后续 Skill 变更必须先改根 `skills/`，再执行 `make sync-skills-dry-run`、`make sync-skills`、`make check-skills`；
   - 不使用 `--prune` 删除 runtime-only vendor Skill，除非已完成许可证和使用影响确认。

2. 调整 Skill 触发策略：
   - 创作生产任务必须优先配对 `context-builder-source-isolation`、`mkaos-knowledge-asset-os`、`review-issue-gate`、`canon-continuity-graph`；
   - 模型调用必须配对 `provider-runtime-policy`；
   - 发布/ReleasePackage 必须配对 `publish-release-gate-os`；
   - 旧式 Markdown 输出只能作为 operator handoff，不作为 production asset 完成标准；
   - `claude-api` 不应覆盖 provider-neutral 或 OpenAI/Codex 任务。

3. 补齐治理记录：
   - 更新 `docs/reports/novel-os-skills-governance-audit.md`，记录本次 drift 修复和 vendor Skill 许可状态；
   - 对 `docx`、`pdf`、`xlsx` 标记专有许可限制；
   - 对 `claude-api`、`mcp-builder` 标记联网/官方文档依赖；
   - 对 `webapp-testing`、`skill-creator` 标记 subprocess/browser/server 生命周期。

4. 维持 Agent-Skill Map 当前方向：
   - `docs/09-skills/agent-skill-map.md` 已覆盖新 Skill；
   - runtime-only 工具 Skill 已单独列出；
   - `provider-runtime-policy`、`publish-release-gate-os`、`canon-continuity-graph` 已加入映射；
   - `narrative-beat-design`、`skill-governance` 已加入映射；
   - 后续新增 `evaluation-benchmark-os`、`source-ingestion-rights-gate` 后再更新映射。

5. 维持外部 writing Skill 决策：
   - 不把 `writing-beats`、`writing-great-skills`、`writing-plans`、`writing-fragments`、`writing-shape` 直接 vendor 到 root `skills/`；
   - `writing-beats` 的 grounding / beat 方法已改写进 `narrative-beat-design`、`chapter-outline`、`long-outline`；
   - `writing-great-skills` 的 predictable / single source of truth / progressive disclosure 方法已改写进 `skill-governance` 和 `usage-policy`；
   - `writing-plans` 的工程计划格式已改写进 `project-planning`；
   - `writing-fragments`、`writing-shape` 暂时保持外部个人写作 Skill。

## 11. 结论

当前 `.claude/skills` 整体适配 Novel Forge v6 / Novel OS，且新增的 MKAOS、Context Builder、ReviewIssue、Agent Loop、Provider Runtime、Canon Continuity、Publish Release Gate、Narrative Beat Design、Skill Governance、Platform Strategy、Engineering Audit 已补上早期主要缺口。

不建议立即删除 Skill。当前最高优先级不是删减，而是持续治理：

1. 保持 root `skills/` 与 `.claude/skills` 无 drift；
2. 所有生产相关 Skill 继续保持 `Novel OS Runtime Contract`；
3. 严格执行 `claude-api` 和 Office/PDF/XLSX 工具 Skill 的 provider、license、subprocess、network 使用边界；
4. 外部个人写作 Skill 继续只做方法参考，不直接进入项目源；
5. 下一步补齐 evaluation benchmark、source ingestion rights、editor chief console 相关 Skill 或测试闭环。
