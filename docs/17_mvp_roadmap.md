# 17. MVP 路线图

## 1. 路线图目标

NovelForge 的最终形态可以很大，但第一阶段必须缩小范围，先验证生产闭环是否能产出有吸引力、可信、不失控的小说内容。

核心原则：

```text
先跑通单本小说前 3 章。
再跑通前 10 章细纲。
再做多项目并行。
最后才做完整 Web 平台。
```

## 2. V1：文件项目制

### 2.1 技术形态

```text
Markdown
JSON
Git
Claude Code
ChatGPT/Codex
DeepSeek
Python 脚本
```

### 2.2 目标

跑通一条完整链路：

```text
创意输入
  ↓
Reader Attraction Gate
  ↓
Project Differentiation Gate
  ↓
Knowledge Compiler
  ↓
Project Constitution
  ↓
Novel Workspace
  ↓
Claude Code 接管
  ↓
前 10 章细纲
  ↓
前 3 章正文 v0/v1/v2
  ↓
审稿
  ↓
反馈模拟
```

### 2.3 必须完成

```text
1. 00_global_assets 小型知识库；
2. 01_world_lab 世界模板库；
3. Reader Attraction Gate；
4. Project Differentiation Gate；
5. Knowledge Compiler 模板；
6. project_constitution.md；
7. 单本小说 Novel Workspace；
8. Claude Code 任务卡；
9. DeepSeek 生成 v0；
10. ChatGPT/Codex 审稿；
11. 反馈分级处理；
12. Git 快照。
```

## 3. V1 验收标准

```text
1. 能从一个创意生成 3 个项目候选；
2. 能通过 Reader Attraction Gate 筛出 1 个强项目；
3. 能通过 Project Differentiation Gate 检查同质化；
4. 能生成 project_knowledge_pack；
5. 能生成 project_constitution.md；
6. 能初始化单本小说 workspace；
7. Claude Code 能接管项目；
8. 能生成前 30 章节奏计划；
9. 能生成前 10 章细纲；
10. 能生成前 3 章正文 v0/v1/v2；
11. 每章都有审稿报告；
12. 能根据模拟评论调整后续 3 章；
13. 不破坏项目宪法。
```

## 4. V2：轻量管理台

### 4.1 技术形态

```text
FastAPI
SQLite / PostgreSQL
简单 Web UI
本地文件 workspace
```

### 4.2 目标

管理多个小说项目、任务、知识卡、审稿报告、评论反馈。

### 4.3 功能范围

```text
项目列表
项目状态
任务卡管理
知识卡浏览
审稿报告查看
反馈记录查看
质量评分看板
```

### 4.4 不做什么

V2 不需要立即做：

```text
复杂权限系统
Kubernetes
完整向量数据库
复杂图谱查询
自动发布平台
多用户协作
```

## 5. V3：完整工业平台

### 5.1 技术形态

```text
Next.js
FastAPI
PostgreSQL
Qdrant
Neo4j
MinIO
Redis
Celery
Claude Agent SDK
```

### 5.2 目标

构建完整工业化系统：

```text
多项目并行调度
通用知识检索
向量库
图谱库
任务队列
权限系统
成本统计
质量看板
反馈闭环
```

## 6. 阶段推进建议

### 阶段 1：文档与模板

完成 docs/、templates/、prompts/ 基础内容。

### 阶段 2：单项目手工闭环

用 Claude Code 手工执行任务卡，生成一部小说的前 3 章。

### 阶段 3：脚本辅助

编写 Python 脚本初始化项目、生成目录、复制模板、更新 registry。

### 阶段 4：轻量 UI

做一个简单管理台，查看项目状态和任务。

### 阶段 5：知识库增强

接入向量检索和知识卡管理。

### 阶段 6：多项目并行

运行主力项目、备用项目、实验项目。

## 7. 失败判断

如果 V1 不能做到以下任意一项，应先修正流程，不要进入 V2：

```text
前 3 章没有明显钩子；
主角欲望不清；
项目宪法无法约束生成；
DeepSeek 生成质量不可控；
ChatGPT/Codex 审稿无法转化成修改；
评论反馈会破坏大纲；
Claude Code 频繁改错文件。
```

## 8. 成功判断

V1 成功标准：

```text
一套项目模板能稳定孵化小说；
前 10 章细纲有追读感；
前 3 章正文能看；
审稿能发现并修复问题；
反馈能影响后续但不失控；
项目 memory 能维持一致性。
```
