# ROADMAP

NovelForge 的路线分为 V1 文件项目制、V2 轻量管理台、V3 完整工业平台。

## V1：文件项目制

目标：不用数据库、不做 Web，先跑通从创意到前三章正文的闭环。

### V1.1 基础工程骨架

- [x] README.md
- [x] docs/
- [x] AGENTS.md
- [x] ROADMAP.md
- [x] CHANGELOG.md
- [x] .env.example
- [x] .gitignore
- [x] pyproject.toml
- [x] Makefile
- [x] scripts/
- [x] tests/
- [x] templates/

### V1.2 文档与模板校验

- [ ] 文档结构校验脚本
- [ ] 模板完整性校验
- [ ] 项目注册表模板
- [ ] 单本小说 workspace 初始化脚本

### V1.3 项目孵化闭环

- [ ] Reader Attraction Gate 模板可用
- [ ] Project Differentiation Gate 模板可用
- [ ] Knowledge Compiler 输出模板可用
- [ ] Project Constitution 模板可用
- [ ] 能从一个创意生成项目骨架

### V1.4 单本小说生产闭环

- [ ] 生成前 30 章节奏计划
- [ ] 生成前 10 章细纲
- [ ] 生成第 1-3 章 v0/v1/v2 目录
- [ ] 生成审稿报告目录
- [ ] 更新 memory 目录
- [ ] 支持模拟反馈处理

### V1.5 Codex / Claude Code 工作流

- [ ] Codex 审查文档合理性
- [ ] Codex 生成工程任务报告
- [ ] Claude Code 接管单本小说 workspace
- [ ] 建立任务卡执行约束

## V2：轻量管理台

目标：在 V1 文件项目制稳定后，增加轻量管理能力。

计划能力：

- 项目列表
- 项目状态
- 任务列表
- 文档索引
- 审稿评分
- 反馈摘要
- 多项目日报

建议技术：

- FastAPI
- SQLite 或 PostgreSQL
- 简单 Web UI
- 本地文件 workspace

## V3：完整工业平台

目标：支持多项目、多知识库、多模型、多任务调度。

计划能力：

- Next.js 前端
- FastAPI 后端
- PostgreSQL 业务库
- Qdrant 向量库
- Neo4j 图谱库
- Redis / Celery 任务队列
- MinIO 文件资产
- 成本统计
- 质量看板
- 多项目调度
- 共享世界分支管理

## 当前优先级

当前只推进 V1。

不要提前引入：

- Web 平台
- 数据库
- 向量数据库
- 图数据库
- 复杂任务队列
- 自动发布系统

## 第一阶段验收标准

V1 阶段必须做到：

1. `make check` 能检查文档与模板结构；
2. `make test` 能运行基础测试；
3. `scripts/init_novel_project.py` 能生成一个单本小说项目骨架；
4. 生成的项目包含 project_constitution、Reader Attraction Gate、任务卡、章节目录；
5. 所有生成内容不包含真实密钥；
6. 能被 Codex / Claude Code 继续接管。
