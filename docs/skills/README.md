# Skills 能力体系

## 1. 模块目标

`skills/` 用于沉淀 NovelForge 中稳定、可复用、可测试的创作能力。

Skill 不是 Agent，也不是知识库或模板。Skill 负责固定一类创作或审稿能力的输入要求、操作流程、输出格式、质量标准和禁止事项。

## 2. 输入

- `CLAUDE.md`
- `AGENTS.md`
- `docs/`
- `templates/`
- `tasks/`
- 项目宪法、世界观、人物卡、大纲、细纲、正文草稿、审稿报告和反馈文件

## 3. 输出

- 可被 Claude Code、Codex、DeepSeek、ChatGPT 或专用 Agent 复用的 Skill 说明。
- Agent 与 Skill 的映射关系。
- 写作流程中的稳定质量门槛。

## 4. 文件路径

```text
skills/
├── hot-novel-deconstruction/
├── anti-copy-abstraction/
├── character-design/
├── worldbuilding/
├── long-outline/
├── chapter-outline/
├── prose-generation/
└── quality-review/

docs/skills/
├── README.md
└── agent-skill-map.md
```

根目录 `skills/` 是项目级 Skill 源目录。`.claude/skills/` 暂不作为权威目录，后续如需接入 Claude Code 运行时，可通过复制或软链接映射到根目录 Skill。

## 5. 执行流程

1. Agent 执行任务前先读取 `CLAUDE.md`、`AGENTS.md`、任务卡和相关项目文件。
2. 根据任务类型选择一个或多个 Skill。
3. 按 Skill 的输入要求检查上下文是否齐备。
4. 按 Skill 的操作流程产出结果。
5. 使用 Skill 的质量标准和禁止事项进行自检。
6. 将结果写入任务卡指定路径，并进入审稿或下一环节。

## 6. 层级关系

```text
CLAUDE.md = 项目总规则
Agent = 岗位角色
Skill = 可复用能力
Knowledge = 素材和知识库
Template = 输出格式
Tool / MCP / Script = 执行动作
Review Gate = 验收标准
```

规则：

- Skills 不替代 Agent。
- Skills 不替代知识库。
- Skills 不保存具体版权内容。
- Skills 负责稳定流程、方法、输出规范和质量标准。
- Agent 调用 Skills 完成岗位任务。
- 正文生产必须经过 `chapter-outline` 和 `quality-review`。
- 热门小说拆解必须经过 `anti-copy-abstraction` 后才能进入下游。
- 读者反馈、作文训练、多学科知识融合是第二阶段 Skills，本次不展开。

## 7. 验收标准

- `skills/` 目录存在。
- 8 个核心 Skill 均包含 `SKILL.md`。
- 每个 `SKILL.md` 都有合法 frontmatter。
- 每个 `SKILL.md` 都包含适用场景、输入要求、操作流程、输出格式、质量标准、禁止事项和与其他模块的关系。
- `make check` 能检查 Skill 目录和基础格式。
- Skill 不保存具体小说全文、具体桥段或版权表达。

## 8. 风险与边界

- Skill 只能保存方法和标准，不能保存私有素材或版权文本。
- Skill 不能绕过项目宪法、任务卡和审稿系统。
- Skill 不能直接授权模型生成 final。
- Skill 与模板职责不同：模板定义格式，Skill 定义如何完成能力。
