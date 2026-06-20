# 10. Claude Code 执行系统

## 1. 模块目标

Claude Code 是单本小说项目的执行总编。

它不负责从零立项，而是接管已经通过项目孵化流程、已经生成项目宪法和项目知识包的 Novel Workspace。

## 2. Claude Code 的职责

```text
1. 读取项目文件；
2. 执行任务卡；
3. 调用 DeepSeek 生成正文 v0；
4. 调用 ChatGPT/Codex 做审稿；
5. 整理修改意见；
6. 生成 v1/v2；
7. 更新 memory；
8. 更新 task 日志；
9. 生成日报和周报；
10. 防止项目偏离项目宪法。
```

## 3. Claude Code 不负责

```text
1. 不负责绕过 Gate 直接立项；
2. 不负责无任务卡自由修改项目；
3. 不负责直接修改 final；
4. 不负责直接修改项目宪法不可修改项；
5. 不负责替代主编做最终发布决策。
```

## 4. 接管前置条件

Claude Code 只接管满足以下条件的项目：

```text
project_constitution.md 已存在；
project_knowledge_pack/ 已存在；
reader_attraction_gate.md 已通过；
project_differentiation_gate.md 已通过；
world_constitution.md 已存在；
commercial_pack.md 已存在；
philosophy_pack.md 已存在；
character_pack.md 已存在；
plot_logic_pack.md 已存在。
```

## 5. 接管第一步

Claude Code 接管项目后，必须生成：

```text
09_reports/project_takeover_report.md
06_memory/current_context.md
08_tasks/current_sprint.md
```

## 6. project_takeover_report.md 模板

```markdown
# Project Takeover Report

## 项目名称

## 当前阶段

## 项目宪法摘要

## 读者吸引力摘要

## 哲学方向摘要

## 世界宪法摘要

## 主角与反派摘要

## 前 10 章目标

## 当前缺失文件

## 当前风险

## 第一阶段任务计划

1.
2.
3.

## Claude Code 执行建议
```

## 7. current_context.md 模板

```markdown
# Current Context

## 当前章节

## 当前主线进度

## 主角状态

## 反派状态

## 已发生关键事件

## 未回收伏笔

## 读者反馈重点

## 后续 3 章目标

## 禁止偏离项
```

## 8. 任务卡制度

Claude Code 每次必须执行任务卡。

禁止输入：

```text
帮我优化这本小说。
```

必须输入：

```text
执行 08_tasks/task_cards/generate_chapter_012_v0.md
```

## 9. 任务卡模板

```markdown
# Task Card

## task_id

generate_chapter_012_v0

## task_type

generate_chapter

## 输入文件

- CLAUDE.md
- PROJECT.md
- project_constitution.md
- project_knowledge_pack/commercial_pack.md
- project_knowledge_pack/plot_logic_pack.md
- 02_outline/chapter_plans/ch012_plan.md
- 06_memory/current_context.md
- 06_memory/unresolved_foreshadowing.md

## 任务目标

生成第 12 章 v0 正文。

## 使用模型

DeepSeek

## 必须遵守

1. 不得修改 final 文件；
2. 不得修改项目宪法；
3. 不得引入未定义新设定；
4. 每章必须包含冲突、推进、奖励、代价、钩子；
5. 结尾必须留追读钩子；
6. 不得复用已有小说具体桥段。

## 输出文件

- 03_chapters/ch012/ch012_v0.md
- 08_tasks/completed.md
- 06_memory/decision_log.md

## 验收标准

1. 字数达到目标；
2. 没有明显 AI 腔；
3. 不违背项目宪法；
4. 至少有一个读者奖励；
5. 结尾有追读钩子。
```

## 10. 权限模式

### 10.1 draft 模式

允许：

```text
读取项目文件；
生成细纲；
生成正文 v0；
更新 memory；
写入 task 日志。
```

禁止：

```text
修改 final；
修改项目宪法；
修改世界第一规则；
删除文件。
```

### 10.2 review 模式

允许：

```text
读取章节；
读取项目宪法；
写入 reviews/；
生成修改建议。
```

禁止：

```text
直接修改正文；
直接修改大纲；
直接修改人物设定。
```

### 10.3 rewrite 模式

允许：

```text
修改指定章节的 v1/v2；
更新审稿报告；
更新 memory。
```

禁止：

```text
修改非指定章节；
修改 final；
修改项目宪法。
```

### 10.4 admin 模式

用于重大重构。

必须人工确认，并生成 constitution_change_proposal.md。

## 11. 每次任务后必须更新

```text
06_memory/current_context.md
06_memory/chapter_summaries.md
06_memory/character_state.md
06_memory/unresolved_foreshadowing.md
06_memory/decision_log.md
08_tasks/completed.md
09_reports/daily_report.md
```

## 12. Git 安全流程

每次执行重要任务：

```text
1. 任务前 commit；
2. 执行任务；
3. 查看 diff；
4. 审查是否违反项目宪法；
5. 人工确认；
6. 任务后 commit。
```

## 13. 验收标准

Claude Code 执行系统可用的标准：

1. 能读取项目宪法；
2. 能读取当前上下文；
3. 能执行任务卡；
4. 能生成指定输出文件；
5. 能更新 memory；
6. 能拒绝越权修改；
7. 能生成审稿与日报；
8. 能维持项目长期一致性。
