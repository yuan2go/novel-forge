# AI Workflow

## 1. 模块目标

本模块定义 `novel-forge` 的 AI 工程协作流程，让 Claude Code、Codex、DeepSeek、ChatGPT 和其他专用代理在 V1 文件项目制内协同工作。

目标不是增加复杂平台，而是把任务拆分、输入输出、权限边界、验收标准和风险控制固定为可重复执行的文件流程。

## 2. 输入

- `AGENTS.md`
- `CLAUDE.md`
- `README.md`
- `ROADMAP.md`
- `docs/`
- `templates/`
- `tasks/`
- 单本小说 workspace 中的任务卡、项目宪法、章节、审稿和反馈文件

## 3. 输出

- 可交给 Codex 执行的工程任务卡
- 可交给 Claude Code 接管的单本小说任务卡
- 可交给 DeepSeek 生成的正文 v0 任务卡
- 可交给 ChatGPT 审稿的评审任务卡
- 统一验收标准和风险边界

## 4. 文件路径

```text
docs/ai-workflow/
├── README.md
├── codex-task-template.md
├── acceptance-criteria.md
└── skill-usage.md

tasks/
├── README.md
├── backlog.md
└── task-template.md
```

## 5. 执行流程

1. 主编或总控 Agent 在 `tasks/backlog.md` 中登记任务。
2. 根据任务类型复制 `tasks/task-template.md` 或 `docs/ai-workflow/codex-task-template.md`。
3. 明确任务目标、允许修改范围、禁止事项、输入文件、输出文件和验收标准。
4. 指派给合适 Agent：Claude Code、Codex、DeepSeek、ChatGPT、知识库 Agent、素材库 Agent 或质量检查 Agent。
5. Agent 执行前先读取 `AGENTS.md`、`CLAUDE.md`、任务卡和必要的 `skills/*/SKILL.md`。
6. 如任务涉及拆书、细纲、正文或审稿，按 `skill-usage.md` 选择并执行 Skill。
7. 执行后输出变更文件列表、diff 摘要、测试结果和未完成风险。
8. 质量检查 Agent 或主编按 `acceptance-criteria.md` 验收。

## 6. 验收标准

- 任务卡存在且边界清晰。
- Agent 只修改授权范围内的文件。
- 不引入 V1 禁止的依赖、数据库或外部服务。
- 新增文档包含目标、输入、输出、路径、流程、验收标准、风险与边界。
- 工程类任务应运行 `make check`，涉及脚本或测试时应运行 `make test`。
- 写作类任务必须经过审稿系统，不得直接进入终稿。
- 热门小说拆解必须经过 `anti-copy-abstraction`。
- 正文生产必须经过 `chapter-outline` 和 `quality-review`。

## 7. 风险与边界

- AI workflow 只定义协作流程，不替代项目宪法。
- 评论反馈不能突破项目宪法。
- 知识库输出不能直接进入正文，必须经过知识编译。
- DeepSeek 初稿不能作为最终稿。
- Codex 不能为了自动化引入 V1 禁止的复杂系统。
- Claude Code 不能无任务卡扩大单本小说 workspace 的修改范围。
