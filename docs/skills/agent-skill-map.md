# Agent 与 Skill 映射

## 1. 模块目标

本文件定义 NovelForge 中 Agent 岗位角色与 `skills/` 可复用能力之间的调用关系，避免 Agent、Skill、Knowledge、Template 和 Tool 职责混淆。

## 2. 输入

- `AGENTS.md`
- `CLAUDE.md`
- `docs/skills/README.md`
- `skills/*/SKILL.md`
- 任务卡和项目文件

## 3. 输出

- Agent 到 Skill 的推荐映射。
- 当前未实现但建议作为第二阶段建设的 Skill。
- 每类 Agent 使用 Skill 时的边界。

## 4. 文件路径

```text
docs/skills/agent-skill-map.md
skills/*/SKILL.md
```

## 5. 执行流程

1. 根据任务卡确定 Agent。
2. 根据本映射选择对应 Skill。
3. 读取 Skill 输入要求，检查是否缺上下文。
4. 执行 Skill 后按任务卡输出。
5. 需要审稿时进入 `quality-review`。

## 6. Agent-Skill 映射

| Agent | 推荐 Skills | 说明 |
|---|---|---|
| 主编 Agent | `quality-review`, `long-outline` | `project-planning` 作为第二阶段规划 Skill，本次不创建空壳。 |
| 拆书 Agent | `hot-novel-deconstruction`, `anti-copy-abstraction` | 拆解结果必须先反抄袭抽象，不能直接进入生成。 |
| 题材策划 Agent | `hot-novel-deconstruction`, `anti-copy-abstraction`, `long-outline` | 使用抽象机制形成题材和长期连载潜力判断。 |
| 世界观 Agent | `worldbuilding` | 每个世界设定必须产生冲突、限制、代价或钩子。 |
| 人物 Agent | `character-design` | 人物行动必须服务主线冲突。 |
| 大纲 Agent | `long-outline`, `character-design`, `worldbuilding` | 大纲必须整合人物、世界规则和商业追读。 |
| 细纲 Agent | `chapter-outline`, `quality-review` | 细纲必须通过章节最小商业单元检查。 |
| 正文 Agent | `prose-generation`, `chapter-outline` | 正文必须严格根据细纲生成，不能绕过审稿。 |
| 审稿 Agent | `quality-review`, `anti-copy-abstraction` | 审稿必须检查原创风险和可执行修改建议。 |
| 反馈 Agent | 第二阶段：`reader-feedback` | 暂不实现，后续结合 `docs/13_feedback_control.md` 建设。 |

## 7. 验收标准

- 每个已实现 Agent 映射至少有一个可用 Skill。
- 任何正文生成任务都能追溯到 `chapter-outline` 和 `quality-review`。
- 任何热门小说拆解都能追溯到 `anti-copy-abstraction`。
- 未实现 Skill 必须标注为第二阶段，不伪装为已完成。

## 8. 风险与边界

- Agent 权限仍以 `AGENTS.md` 为准，Skill 不能扩大权限。
- Skill 不保存知识库内容，只保存能力流程。
- 反馈、作文训练和多学科知识融合暂不扩展，避免空泛 Skill。
