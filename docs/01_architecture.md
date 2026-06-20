# 01. 总体架构设计

## 1. 架构目标

NovelForge 的架构目标是把小说生产拆成多个可独立维护的模块，让通用知识、项目孵化、单本小说执行、反馈演化互不污染。

核心目标：

1. 通用知识可以长期沉淀；
2. 每本小说可以独立执行；
3. 多本小说可以并行生产；
4. 世界模板可以复用但不会强行套用；
5. 评论可以影响小说但不会让小说失控；
6. 模型可以切换但项目规则保持稳定。

## 2. 五层架构

```text
NovelForge Universe Factory
│
├── L1 全局资产层 Global Assets
│   ├── 网文商业结构库
│   ├── 多学科可信度知识库
│   ├── 哲学命题库
│   ├── 世界模板库
│   ├── 读者反馈规律库
│   └── 审稿规则库
│
├── L2 项目孵化层 Project Incubation
│   ├── 总编 Agent
│   ├── 读者吸引力 Gate
│   ├── 项目差异化 Gate
│   ├── 知识编译器
│   ├── 世界选择器
│   ├── 哲学方向选择器
│   └── 项目宪法生成器
│
├── L3 单本小说项目层 Novel Workspace
│   ├── CLAUDE.md
│   ├── PROJECT.md
│   ├── project_constitution.md
│   ├── project_knowledge_pack/
│   ├── bible/
│   ├── outline/
│   ├── chapters/
│   ├── reviews/
│   ├── feedback/
│   └── memory/
│
├── L4 执行生产层 Production Execution
│   ├── Claude Code 项目总编
│   ├── DeepSeek 初稿与批处理
│   ├── ChatGPT/Codex 高质量审稿
│   ├── 任务卡系统
│   ├── Git 快照与回滚
│   └── 质量评分系统
│
└── L5 反馈进化层 Feedback Evolution
    ├── 项目私有反馈
    ├── 反馈分级决策
    ├── 后续 3-10 章调整
    ├── 全局反馈规律沉淀
    └── 多项目质量复盘
```

## 3. 数据流

```text
用户创意
  ↓
总编 Agent 访谈
  ↓
生成项目候选
  ↓
Reader Attraction Gate 评分
  ↓
Project Differentiation Gate 检查
  ↓
检索全局资产
  ↓
Knowledge Compiler 编译项目知识包
  ↓
生成 Project Constitution
  ↓
初始化 Novel Workspace
  ↓
Claude Code 按任务卡执行
  ↓
DeepSeek 生成正文 v0
  ↓
ChatGPT/Codex 审稿
  ↓
Claude Code 修改与更新 memory
  ↓
发布与收集评论
  ↓
反馈控制系统处理
  ↓
项目内调整 / 全局知识回流
```

## 4. 模块边界

### 4.1 全局资产层边界

全局资产层只能保存抽象知识：

```text
结构
规律
机制
检查项
模板
审稿规则
```

禁止保存或复用：

```text
具体桥段
具体台词
具体人物
具体案件
具体反转
已有作品独特设定
```

### 4.2 项目孵化层边界

项目孵化层负责将创意变成可执行项目，但不负责写正文。

输出必须是：

```text
reader_attraction_gate.md
project_differentiation_gate.md
project_knowledge_pack/
project_constitution.md
```

### 4.3 Novel Workspace 边界

每本小说独立项目目录，不能共享 memory、chapters、feedback、reviews。

共享世界只能通过 world branch 或 world_pack 引用，不能直接改共享世界主线。

### 4.4 执行生产层边界

Claude Code 只能根据任务卡执行。DeepSeek 负责生产，ChatGPT/Codex 负责高质量判断。

任何模型都不能绕过项目宪法。

### 4.5 反馈进化层边界

评论默认只影响后续 3-10 章，不直接改变项目宪法、世界宪法、哲学终局和主角核心欲望。

## 5. 技术演进

### V1：文件项目制

```text
Markdown + JSON + Git + Claude Code + ChatGPT/Codex + DeepSeek
```

### V2：轻量管理台

```text
FastAPI + SQLite/PostgreSQL + 简单 Web UI + 本地 workspace
```

### V3：完整工业平台

```text
Next.js + FastAPI + PostgreSQL + Qdrant + Neo4j + MinIO + Redis + Celery + Claude Agent SDK
```

## 6. 架构验收标准

一个架构版本必须满足：

1. 能创建项目候选；
2. 能通过吸引力 Gate 筛选；
3. 能通过差异化 Gate 防同质化；
4. 能把全局知识编译成项目知识包；
5. 能生成项目宪法；
6. 能初始化单本小说 workspace；
7. Claude Code 能接管并执行任务卡；
8. 能生成正文、审稿、修改、更新 memory；
9. 能处理评论反馈；
10. 能把稳定反馈沉淀回全局资产。
