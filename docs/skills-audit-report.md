# .claude Skills Audit Report

日期：2026-07-05

## 1. 审计范围

本报告基于当前项目 `.claude/skills/` 目录做只读分析，未修改任何 Skill 内容。

已检查：

- `.claude/skills/*/SKILL.md`
- `.claude/skills/*/LICENSE.txt`
- `.claude/skills/*/scripts/*`
- `.claude/skills/*/reference/*`
- `docs/09-skills/agent-skill-map.md`
- `AGENTS.md`

当前 `.claude/skills` 共 23 个 Skill：

- 项目小说工业化 Skill：14 个
- 通用 / 官方 / 工具型 Skill：9 个

## 2. 总体结论

当前 Skill 集合整体适配 Novel Forge / Novel OS：

- 小说生产主链 Skill 覆盖 Topic、World、Character、Outline、ChapterPlan、Prose、Review、Feedback、Knowledge、Material、Training。
- 通用 Skill 覆盖 Claude API、MCP、PDF、DOCX、XLSX、前端设计、Web 测试、文档协作、Skill 创建。
- 未发现明显恶意命令、未知二进制或自动执行外部联网行为。
- 风险主要来自：
  - Office / PDF / XLSX / Claude API 的专有许可证和再分发边界；
  - `claude-api`、`mcp-builder`、`doc-coauthoring` 中的外部文档 / API / WebFetch 依赖；
  - `skill-creator`、`webapp-testing`、`docx`、`xlsx` 脚本会启动 subprocess、浏览器、LibreOffice、测试服务器或 CLI；
  - 项目自定义 Skill 缺少独立 LICENSE 文件和机器可读版本元数据。

建议：全部保留，但对工具型 Skill 增加使用策略；新增 Novel OS 工程治理类 Skill。

## 3. Skill 清单与适配度矩阵

| Skill | 类型 | 用途 | 项目适配度 | 脚本/依赖 | 风险级别 | 建议 |
| -- | -- | -- | -- | -- | -- | -- |
| `anti-copy-abstraction` | 项目小说 | 将具体参考作品拆解转成不可复原的抽象机制 | 高 | 无脚本 | 低 | 保留 |
| `hot-novel-deconstruction` | 项目小说 | 拆解爆款结构、节奏、爽点、商业逻辑 | 高 | 无脚本 | 中 | 保留；必须和 anti-copy 连用 |
| `multidisciplinary-knowledge` | 项目小说 / MKAOS | 将专业知识转成故事规则、冲突和审稿检查 | 高 | 无脚本 | 中 | 保留；建议升级为 MKAOS 专用 Skill |
| `material-curation` | 项目小说 / 资产 | 整理素材、知识、拆解结果，避免 raw source 进入生成 | 高 | 无脚本 | 低 | 保留 |
| `topic-development` | 项目小说 | 题材、市场定位、差异化和原创边界 | 高 | 无脚本 | 低 | 保留 |
| `worldbuilding` | 项目小说 | 世界规则、资源、阶层、组织、代价机制 | 高 | 无脚本 | 低 | 保留 |
| `character-design` | 项目小说 | 人物目标、欲望、压力、关系和成长弧 | 高 | 无脚本 | 低 | 保留 |
| `long-outline` | 项目小说 | 全书 / 卷纲 / 长线弧光 / 伏笔规划 | 高 | 无脚本 | 低 | 保留 |
| `chapter-outline` | 项目小说 | 章节细纲、冲突、信息增量、钩子和承接 | 高 | 无脚本 | 低 | 保留 |
| `prose-generation` | 项目小说 | 基于已批准细纲生成正文候选 | 高 | 无脚本 | 中 | 保留；必须接 ContextBuilder / ReviewGate |
| `quality-review` | 项目小说 / 审稿 | 审查逻辑、节奏、原创风险、商业弱点 | 高 | 无脚本 | 低 | 保留 |
| `reader-feedback` | 项目小说 / 反馈 | 导入、分类、采纳或拒绝读者反馈 | 高 | 无脚本 | 低 | 保留 |
| `project-planning` | 工程 / 产品 | 阶段规划、任务拆解、P0/P1/P2、验收标准 | 高 | 无脚本 | 低 | 保留 |
| `training-exercise` | 训练题 | 作文、阅读、翻译、批改标准 | 中 | 无脚本 | 低 | 保留；非主链但有 MKAOS training 价值 |
| `claude-api` | 官方通用 | Claude / Anthropic SDK、模型、MCP、token、迁移参考 | 中 | 大量 reference，无脚本 | 中 | 保留但限定触发；避免覆盖 OpenAI/Codex 路线 |
| `mcp-builder` | 官方通用 | MCP Server 设计、实现、测试和评估 | 高 | Python eval 脚本，依赖 `anthropic`, `mcp` | 中 | 保留；外部 API 必须 opt-in |
| `webapp-testing` | 官方通用 | Playwright 本地 Web 测试、截图、日志 | 高 | `with_server.py` 启动 subprocess/server | 中 | 保留；只跑本地服务 |
| `frontend-design` | 官方通用 | UI 视觉设计、排版、交互设计判断 | 中 | 无脚本 | 低 | 保留；需服从本项目 UI 约束 |
| `docx` | 官方通用 | Word 文档读写、批注、修订、转换 | 中 | 59 个脚本 / LibreOffice / npm docx | 中 | 保留但按需使用；注意专有许可证 |
| `pdf` | 官方通用 | PDF 读取、拆分、合并、表单、OCR、生成 | 中 | 8 个脚本 / pypdf / pdfplumber / OCR 可选依赖 | 中 | 保留；适合专业书导入辅助 |
| `xlsx` | 官方通用 | Excel / CSV / TSV 读写、公式、建模 | 中 | 52 个脚本 / LibreOffice / pandas 等 | 中 | 保留但非核心 |
| `doc-coauthoring` | 官方通用 | 文档协作流程、读者测试、上下文收集 | 中 | 无脚本 | 中 | 候选保留；与 project-planning 重叠 |
| `skill-creator` | 官方通用 | 创建、评测、优化 Skill | 中 | 9 个脚本，可能调用 `claude -p` / browser | 中 | 保留；只在 Skill 开发时触发 |

## 4. 用途分组

### 4.1 Novel OS 小说生产主链

对应 `docs/09-skills/agent-skill-map.md` 的主链：

- `topic-development`
- `worldbuilding`
- `character-design`
- `long-outline`
- `chapter-outline`
- `prose-generation`
- `quality-review`
- `reader-feedback`

这些 Skill 与 Novel Forge 的 Topic / World / Character / Outline / ChapterPlan / Draft / Review / Feedback 资产链一致，适配度最高。

### 4.2 MKAOS / 知识资产治理

- `hot-novel-deconstruction`
- `anti-copy-abstraction`
- `multidisciplinary-knowledge`
- `material-curation`
- `training-exercise`

这些 Skill 与 MKAOS 的 Source -> Knowledge -> Material -> Usage -> Review -> Feedback 思路一致。当前缺点是它们仍是通用人工工作流描述，没有显式绑定：

- `KnowledgeCard`
- `CreativeKnowledgeCard`
- `SourceEvidenceSpan`
- `KnowledgePack`
- `ContextBundle`
- `ReviewIssue`
- `MutationAudit`
- `LineageAudit`

### 4.3 工程 / Agent / MCP / UI

- `project-planning`
- `claude-api`
- `mcp-builder`
- `webapp-testing`
- `frontend-design`
- `skill-creator`

这些 Skill 适合当前工程继续做 Agent Center、MCP、UI 控制台、测试和 Skill 体系演进。

### 4.4 文档与文件处理

- `doc-coauthoring`
- `docx`
- `pdf`
- `xlsx`

这些 Skill 对专业书导入、报告生成、外部资料处理有价值，但不是 Novel OS 主链必需项。

## 5. 重复项与重叠分析

| 重叠组 | 涉及 Skill | 判断 | 建议 |
| -- | -- | -- | -- |
| 规划与文档协作 | `project-planning`, `doc-coauthoring` | 部分重叠。前者偏工程任务和验收，后者偏文档写作流程。 | 都保留；工程任务优先 `project-planning`，正式长文档可用 `doc-coauthoring`。 |
| 参考拆解到知识资产 | `hot-novel-deconstruction`, `anti-copy-abstraction`, `material-curation`, `multidisciplinary-knowledge` | 高度连续，不是重复。 | 保留；建议新增 MKAOS 编排 Skill，把四者串成 Source -> KnowledgePack 流程。 |
| 大纲链路 | `long-outline`, `chapter-outline`, `prose-generation`, `quality-review` | 分工清晰。 | 保留；禁止 prose-generation 绕过 chapter-outline 和 quality-review。 |
| 文件处理 | `pdf`, `docx`, `xlsx` | 不同格式，不重复。 | 保留；只在文件任务触发，避免常规工程任务误触发。 |
| UI 工作 | `frontend-design`, `webapp-testing` | 一个设计，一个验证。 | 都保留；UI 改造后应搭配使用。 |
| Agent/API/MCP | `claude-api`, `mcp-builder`, `skill-creator` | 都与 Agent/Skill 生态有关，但目标不同。 | 保留；外部 provider 和联网动作必须显式 opt-in。 |

## 6. 风险项

| 风险项 | 涉及 Skill | 说明 | 建议控制 |
| -- | -- | -- | -- |
| 专有许可证 / 不宜再分发 | `claude-api`, `docx`, `pdf`, `xlsx` | LICENSE 指向 Anthropic 服务条款或专有条款；不应从 `.claude/skills` 中抽取再分发。 | 保留 runtime 使用；不要复制到公开包或二次发布。 |
| 外部联网 / WebFetch 依赖 | `claude-api`, `mcp-builder`, `doc-coauthoring` | 文档建议读取官方在线文档、Claude 页面或连接器。 | 默认本地只读；联网必须用户明确请求或任务需要。 |
| API key / token 示例 | `claude-api`, `mcp-builder` | 文档含 `ANTHROPIC_API_KEY`、Bearer token、OAuth 示例。未发现真实密钥。 | 保留；禁止把示例 token 写入代码或日志。 |
| subprocess / server 生命周期 | `webapp-testing`, `skill-creator`, `docx`, `xlsx` | 脚本会启动浏览器、server、LibreOffice、`claude -p` 或子进程。 | 只在明确任务中运行；生产路径不自动调用。 |
| 依赖安装 | `docx`, `pdf`, `xlsx`, `mcp-builder`, `webapp-testing` | 可能需要 npm、LibreOffice、pandas、pypdf、Playwright、anthropic/mcp。 | 按项目依赖管理显式安装；不要让默认测试依赖这些外部工具。 |
| 大体积 Skill 污染上下文 | `docx`, `xlsx`, `claude-api`, `skill-creator` | `SKILL.md` 较长，且资源多。 | 遵守 progressive disclosure，只读相关 reference。 |
| 与 Codex/OpenAI 路线冲突 | `claude-api` | 该 Skill 强触发 Claude/Anthropic 实现，可能不适合 OpenAI/Codex API 任务。 | 若任务明确 OpenAI/Codex，不使用该 Skill；保留其 skip 规则。 |
| 小说版权边界 | `hot-novel-deconstruction`, `prose-generation`, `material-curation` | 参考作品拆解可能误入仿写。 | 必须先过 `anti-copy-abstraction` 和 `quality-review`。 |
| 缺 LICENSE 文件 | 14 个项目自定义小说 Skill | 无独立 LICENSE；可视为项目内部资料，但再分发边界不清。 | 建议在根 `skills/` 或 docs 统一声明项目 Skill 许可证和同步策略。 |

## 7. 保留建议

### 必须保留

- `anti-copy-abstraction`
- `hot-novel-deconstruction`
- `multidisciplinary-knowledge`
- `material-curation`
- `topic-development`
- `worldbuilding`
- `character-design`
- `long-outline`
- `chapter-outline`
- `prose-generation`
- `quality-review`
- `reader-feedback`
- `project-planning`
- `webapp-testing`
- `mcp-builder`

理由：这些 Skill 直接支撑 Novel OS 的创作主链、MKAOS 知识治理、UI/测试和 MCP 扩展。

### 建议保留但限域触发

- `claude-api`：仅在 Claude / Anthropic SDK 或 Anthropic provider 工作中使用。
- `frontend-design`：仅在 UI 设计或重构中使用，并服从本项目本地小说工厂 UI 约束。
- `docx` / `pdf` / `xlsx`：仅在明确文件处理任务中使用。
- `doc-coauthoring`：仅在长文档协作、RFC、PRD、技术方案时使用。
- `skill-creator`：仅在创建或优化 Skill 时使用。
- `training-exercise`：保留为训练题和教育场景扩展能力。

## 8. 删除建议

当前不建议立即删除任何 Skill。

可选瘦身策略：

| 删除候选 | 条件 | 影响 |
| -- | -- | -- |
| `doc-coauthoring` | 如果项目不再做长文档协作，只用 `project-planning` 输出工程报告 | 减少一个通用文档流程，但会降低文档共创质量。 |
| `xlsx` | 如果项目不处理表格交付物或财务模型 | 减少 1.2M runtime 体积；会损失 XLSX/CSV 清洗能力。 |
| `docx` | 如果不生成 Word 报告或评审文档 | 减少 1.2M runtime 体积；会损失 DOCX 读写与批注能力。 |
| `claude-api` | 如果当前环境只允许 OpenAI/Codex，不做 Claude provider | 减少 920K 文档；会损失 Anthropic provider 最新 API 参考。 |
| `skill-creator` | 如果不在项目内开发自定义 Skill | 减少 248K；会损失 Skill eval/packaging 辅助。 |

如果删除，应通过项目约定的同步机制处理，不要直接手工删 runtime copy。`AGENTS.md` 已说明 runtime copies under `.claude/skills/` should be generated from root `skills/` using `make sync-skills`。

## 9. 新增建议

当前缺少面向 Novel OS 工程治理的专用 Skill。建议新增以下 Skill 到根 `skills/`，再同步到 `.claude/skills/`：

| 建议 Skill | 用途 | 触发场景 | 优先级 |
| -- | -- | -- | -- |
| `novel-os-engineering-audit` | 审计代码、docs、tests 是否符合 Novel OS runtime 边界 | 用户要求工程审计、P0/P1/P2 对齐、完成度评分 | P0 |
| `mkaos-knowledge-asset-os` | 将来源导入、证据层、抽象知识、图谱、pack、feedback 串成 MKAOS 操作流程 | MKAOS 导入、专业书抽取、知识图谱、source isolation | P0 |
| `context-builder-source-isolation` | 检查 ContextBundle、RAG、prompt preview 是否泄露 raw source | Context Builder、RAG、prose、publish、recap 相关任务 | P0 |
| `review-issue-gate` | 将 MKAOS/Canon/Eval/Review issue 转成阻断和修订任务 | ReviewIssue、Publish Gate、Release Package、Loop Kernel | P1 |
| `agent-loop-governance` | AgentRun、LoopRun、AuditLog、Eval、Rollback 的治理闭环 | Agent Center、Loop Kernel、Workflow 主链迁移 | P1 |
| `platform-strategy-os` | 起点、番茄、飞卢、晋江、知乎盐选、出版向平台策略 | 平台适配、大纲节奏、发布门禁、反馈回流 | P1 |
| `editor-chief-console-eval` | 总编控制台健康度、风险、下 10 章策略和发布判断 | Editor-in-Chief Console、质量总览、可继续生产判断 | P1 |
| `local-provider-runtime-policy` | provider hard-stop、fallback approval、cost/timeout/token boundary | 模型适配、provider fallback、生产 fail-closed | P1 |

## 10. 具体整改建议

1. 在 `docs/09-skills/agent-skill-map.md` 补充通用 Skill 映射：
   - Engineering Agent：`mcp-builder`, `webapp-testing`, `frontend-design`
   - Model Evaluation Agent：`claude-api`
   - Documentation Agent：`doc-coauthoring`, `docx`, `pdf`, `xlsx`
   - Skill Governance Agent：`skill-creator`

2. 给项目自定义小说 Skill 增加统一许可证说明：
   - 可在根 `skills/README.md` 或 `docs/09-skills/runtime-sync.md` 写明项目内部 Skill 版权和同步方式。
   - 不建议逐个改 `.claude/skills` runtime copy。

3. 给高风险工具型 Skill 增加项目使用策略文档：
   - 何时可以运行脚本；
   - 何时需要用户确认；
   - 外部联网、API key、provider 调用、依赖安装的边界。

4. 对 `claude-api` 设置触发边界：
   - 仅处理 Anthropic/Claude provider；
   - OpenAI/Codex 任务使用项目默认工程指令或 OpenAI docs skill，不被 `claude-api` 覆盖。

5. 对小说主链 Skill 增加 Novel OS 资产名映射：
   - TopicSeed、WorldRuleCard、CharacterCard、Outline、ChapterPlan、DraftChapter、ReviewIssue、RevisionTask、FeedbackInsight、KnowledgeCard。

## 11. 结论

当前 `.claude/skills` 不是无脑堆叠，整体与 Novel Forge 的本地小说操作系统方向匹配。最有价值的是 14 个项目小说工业化 Skill 和 `webapp-testing` / `mcp-builder` / `project-planning`。

不建议立即删除 Skill。下一步更有价值的工作是：

1. 新增 MKAOS / Context Builder / ReviewIssue / Agent Loop / Platform Strategy 等 Novel OS 专用 Skill；
2. 把项目自定义 Skill 从人工写作流程升级为 schema-backed、gate-aware、source-isolated 的操作流程；
3. 补齐 Skill 使用策略、许可证边界和 Agent-Skill Map；
4. 保持 `.claude/skills` 作为 runtime copy，不直接手工编辑，后续从根 `skills/` 同步。
