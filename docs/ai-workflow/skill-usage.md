# Skill Usage Workflow

## 1. 模块目标

本文件说明 Claude Code、Codex、DeepSeek、ChatGPT 和其他 Agent 如何在现有 AI workflow 中调用 `skills/`。

## 2. 输入

- `AGENTS.md`
- `CLAUDE.md`
- `docs/skills/README.md`
- `docs/skills/agent-skill-map.md`
- `skills/*/SKILL.md`
- 当前任务卡和目标文件

## 3. 输出

- 带 Skill 依据的任务执行结果。
- 可审计的创作流程。
- 可复用的质量门槛。

## 4. 文件路径

```text
docs/ai-workflow/skill-usage.md
skills/
tasks/
```

## 5. 执行流程

1. 读取任务卡，确认任务目标、输入、输出、允许修改范围和禁止事项。
2. 根据 `docs/skills/agent-skill-map.md` 选择 Skill。
3. 读取对应 `SKILL.md`。
4. 检查 Skill 输入要求是否满足。
5. 按 Skill 操作流程执行。
6. 按 Skill 输出格式写入指定文件。
7. 按 Skill 质量标准自检。
8. 涉及正文或高风险拆解时，进入 `quality-review` 或 `anti-copy-abstraction`。

## 6. 常见路由

```text
热门小说拆解
  → hot-novel-deconstruction
  → anti-copy-abstraction
  → 题材 / 素材 / 知识库

全书规划
  → character-design
  → worldbuilding
  → long-outline
  → quality-review

章节生产
  → chapter-outline
  → prose-generation
  → quality-review

原创风险审查
  → anti-copy-abstraction
  → quality-review
```

## 7. 验收标准

- 任务报告中应说明使用了哪些 Skill。
- 正文生成任务不得跳过 `chapter-outline`。
- 正文产物不得跳过 `quality-review`。
- 热门小说拆解不得跳过 `anti-copy-abstraction`。
- DeepSeek 产出的正文 v0 不能直接进入 final。

## 8. 风险与边界

- Skill 只规定方法，不授权越权修改。
- Skill 不替代项目宪法。
- Skill 不保存具体小说内容。
- Skill 输出必须服从任务卡路径和项目文件边界。
