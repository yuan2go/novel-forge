# Skills System Architecture

## 1. 模块目标

Skills System 是 NovelForge 在 V1 文件项目制中的能力层，用于把稳定创作流程沉淀为可复用、可审计、可检查的 Markdown Skill。

它补足 V1 中 Agent 有岗位、Template 有格式、Knowledge 有素材，但缺少“稳定能力流程”的空白。

## 2. 输入

- `CLAUDE.md` 项目总规则
- `AGENTS.md` Agent 岗位权限
- `docs/` 业务流程和风险控制
- `templates/` 输出格式
- `skills/*/SKILL.md` 能力流程

## 3. 输出

- 项目级 Skill 目录。
- Skill 格式约束。
- Agent 调用 Skill 的架构边界。

## 4. 文件路径

```text
skills/
docs/skills/
docs/architecture/skills-system.md
docs/ai-workflow/skill-usage.md
```

## 5. 执行流程

```text
任务卡
  → 选择 Agent
  → 选择 Skill
  → 读取 Knowledge / Template / 项目文件
  → 执行 Skill 流程
  → 输出到任务指定路径
  → Review Gate
```

## 6. 架构边界

| 层级 | 职责 | 示例 |
|---|---|---|
| `CLAUDE.md` | 项目最高协作规则 | 禁止事项、测试命令、总控规则 |
| Agent | 岗位角色和权限 | 主编、拆书、正文、审稿、质量检查 |
| Skill | 可复用能力流程 | 拆书、反抄袭抽象、细纲、正文、审稿 |
| Knowledge | 素材和知识资产 | 结构卡、知识卡、世界模板 |
| Template | 输出格式 | 章节细纲、审稿报告、任务卡 |
| Tool / Script | 执行动作 | `make check`、初始化脚本 |
| Review Gate | 验收标准 | 商业审稿、原创风险审稿、质量门禁 |

## 7. 根目录 `skills/` 与 `.claude/skills/`

当前权威目录是：

```text
skills/
```

原因：

1. 项目使用文件项目制，根目录 Skill 可被 Git 管理和测试。
2. Skill 是项目资产，不应只存在于本地 Claude Code 配置。
3. `.claude/skills/` 适合作为运行时映射目录，后续可通过复制或软链接接入。

## 8. 验收标准

- 所有核心 Skill 必须有 `SKILL.md`。
- 所有核心 Skill 必须有 YAML frontmatter。
- 所有核心 Skill 必须包含输入、流程、输出、质量标准和禁止事项。
- 结构检查脚本必须覆盖核心 Skill。
- Skill 不能保存具体版权内容。

## 9. 风险与边界

- 不把 Skill 做成复杂 Agent 平台。
- 不在 Skill 中写真实素材、密钥或版权文本。
- 不让 Skill 代替审稿结论。
- 不用 Skill 绕过项目宪法和任务卡。
