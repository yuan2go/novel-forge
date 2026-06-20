# 09. Novel Workspace 单本小说项目结构

## 1. 模块目标

Novel Workspace 是单本小说的独立工作区。

每一本小说都必须拥有自己的 workspace，保存从立项、设定、大纲、章节、审稿、反馈到复盘的全部文件。

## 2. 核心原则

```text
每本小说是一个独立项目。
每本小说有自己的项目宪法。
每本小说有自己的 memory。
每本小说有自己的反馈和审稿。
共享知识只能通过项目知识包进入。
```

## 3. 标准目录结构

```text
project_001_black_archive/
├── CLAUDE.md
├── PROJECT.md
├── project_constitution.md
├── project_knowledge_pack/
│   ├── commercial_pack.md
│   ├── philosophy_pack.md
│   ├── credibility_pack.md
│   ├── world_pack.md
│   ├── character_pack.md
│   ├── plot_logic_pack.md
│   ├── style_pack.md
│   ├── feedback_control_pack.md
│   └── originality_risk_pack.md
│
├── 00_project_gate/
│   ├── reader_attraction_gate.md
│   ├── project_differentiation_gate.md
│   ├── project_kill_check.md
│   └── project_approval.md
│
├── 01_bible/
│   ├── world_constitution.md
│   ├── world_rules.md
│   ├── power_system.md
│   ├── economy_system.md
│   ├── political_system.md
│   ├── social_structure.md
│   ├── law_system.md
│   ├── geography_ecology.md
│   ├── characters.md
│   ├── factions.md
│   ├── timeline.md
│   └── contradiction_rules.md
│
├── 02_outline/
│   ├── book_outline.md
│   ├── volume_001.md
│   ├── serialization_plan.md
│   └── chapter_plans/
│       ├── ch001_plan.md
│       └── ch002_plan.md
│
├── 03_chapters/
│   ├── ch001/
│   │   ├── ch001_plan.md
│   │   ├── ch001_v0.md
│   │   ├── ch001_v1.md
│   │   ├── ch001_v2.md
│   │   └── ch001_final.md
│
├── 04_reviews/
│   ├── ch001/
│   │   ├── commercial_review.md
│   │   ├── logic_review.md
│   │   ├── psychology_review.md
│   │   ├── world_review.md
│   │   └── final_review.md
│
├── 05_feedback/
│   ├── raw_comments.jsonl
│   ├── feedback_analysis.md
│   ├── feedback_decision.md
│   └── outline_adjustment.md
│
├── 06_memory/
│   ├── current_context.md
│   ├── chapter_summaries.md
│   ├── character_state.md
│   ├── unresolved_foreshadowing.md
│   ├── resolved_foreshadowing.md
│   ├── decision_log.md
│   └── canon_changes.md
│
├── 07_style/
│   ├── style_guide.md
│   ├── dialogue_rules.md
│   ├── scene_templates.md
│   └── forbidden_ai_tone.md
│
├── 08_tasks/
│   ├── current_sprint.md
│   ├── todo.md
│   ├── completed.md
│   └── task_cards/
│
└── 09_reports/
    ├── project_takeover_report.md
    ├── daily_report.md
    ├── weekly_report.md
    └── quality_dashboard.md
```

## 4. 核心文件说明

### 4.1 CLAUDE.md

定义 Claude Code 在本项目中的身份、权限和执行规则。

### 4.2 PROJECT.md

定义项目基础信息：名称、类型、状态、连载目标、模型路由、当前阶段。

### 4.3 project_constitution.md

单本小说最高规则。

### 4.4 project_knowledge_pack/

由 Knowledge Compiler 生成，保存本书专属知识包。

### 4.5 00_project_gate/

保存立项前置检查结果。

### 4.6 01_bible/

保存世界观、人物、势力、历史、规则等长期设定。

### 4.7 02_outline/

保存整书大纲、卷纲、连载节奏计划和章节细纲。

### 4.8 03_chapters/

保存正文不同版本。

### 4.9 04_reviews/

保存审稿报告。

### 4.10 05_feedback/

保存评论、反馈分析、反馈采纳决策和大纲调整建议。

### 4.11 06_memory/

保存项目运行中需要反复读取的长期记忆。

### 4.12 07_style/

保存语言风格、对白规则、场景模板、AI 腔禁用规则。

### 4.13 08_tasks/

保存任务卡和当前生产计划。

### 4.14 09_reports/

保存接管报告、日报、周报、质量看板。

## 5. 文件真相源原则

V1 阶段采用文件为主真相源。

```text
project_constitution.md
01_bible/
02_outline/
03_chapters/
06_memory/
```

这些文件是主数据。

数据库或 Web 平台只作为索引、展示和任务状态管理。

## 6. Git 快照规则

每次重要任务必须：

```text
任务前 commit
任务后 diff
审查后确认
必要时 revert
```

建议提交信息格式：

```text
feat(project): generate chapter 012 v0
docs(project): update world constitution
review(chapter): add logic review for ch003
feedback(project): adjust outline from reader comments
```

## 7. final 文件保护

```text
*_final.md 默认只读。
修改 final 必须有人工主编确认。
Claude Code 不能自动覆盖 final。
```

## 8. 验收标准

一个 Novel Workspace 必须满足：

1. 有完整 project_constitution.md；
2. 有 project_knowledge_pack；
3. 有 CLAUDE.md；
4. 有 PROJECT.md；
5. 有 world_constitution.md；
6. 有 characters.md；
7. 有 serialization_plan.md；
8. 有 current_context.md；
9. 有 task_cards；
10. Claude Code 可以根据这些文件接管项目。
