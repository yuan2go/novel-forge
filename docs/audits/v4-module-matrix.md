# V4 Module Matrix

## 1. 模块目标

用矩阵方式审计 V4 小说工厂各业务模块的当前状态、证据、缺口、风险和建议优先级。

## 2. 输入

- `docs/novel-forge-v4-final.md`
- `docs/00_overview.md` 到 `docs/18_templates.md`
- `docs/ai-workflow/`
- `scripts/`
- `templates/`
- `tests/`

## 3. 输出

V4 模块状态矩阵。

## 4. 文件路径

`docs/audits/v4-module-matrix.md`

## 5. 执行流程

1. 按用户要求列出核心模块。
2. 对照文档和源码判断实现状态。
3. 标出涉及文档、涉及代码、缺口和风险。
4. 给出建议优先级。

## 6. 验收标准

- 覆盖用户指定的所有模块。
- 不把“文档设计”误判为“功能实现”。
- 每行包含可追踪证据路径。

## 7. 风险与边界

本矩阵只做审计，不执行架构迁移。

| 模块 | 当前状态 | 涉及文档 | 涉及代码 | 已实现内容 | 缺口 | 风险 | 建议优先级 |
|---|---|---|---|---|---|---|---|
| 热门小说拆解 | 仅有设计 | `docs/novel-forge-v4-final.md` 第 12 节、`docs/02_global_assets.md` | 无 | 定义拆解目标、流程、报告结构 | 无 `data/raw/novels/`、无拆解脚本、无 schema、无样例 | 无法转化为可复用商业资产；版权边界无法校验 | P0 |
| 专业知识书籍解析 | 仅有设计 | V4 第 13 节、`docs/02_global_assets.md`、`docs/07_knowledge_compiler.md` | 无 | 定义概念卡、因果链、叙事功能 | 无 `data/raw/books/`、无知识卡 schema、无解析流程 | 多学科知识无法稳定进入创作系统 | P1 |
| 多学科知识库 | 仅有设计 | V4 第 9 节、`docs/02_global_assets.md` | 无 | 学科范围、知识卡模板、使用原则清晰 | 无 `knowledge/discipline/` 目录、无来源元数据、无校验 | 知识可能堆设定或污染正文 | P0 |
| 素材库 | 尚未实现 | V4 第 4、6、22 节 | 无 | 定义原始素材、清洗文本、chunks、metadata | 无 `data/` 目录、无导入/清洗/切分脚本 | 原文、摘录、拆解混放会带来版权和数据污染风险 | P0 |
| 题材库 | 仅有设计 | V4 第 14 节、`docs/04_project_incubation.md` | 无 | 题材卡结构、评估标准 | 无 `factory/topics/`、无题材生成和评分入口 | 无法从拆解资产转为原创项目候选 | P0 |
| 世界观 | 部分实现 | `docs/03_world_lab.md`、`docs/09_novel_workspace.md`、V4 第 15 节 | `scripts/init_novel_project.py` | 初始化脚本创建 `01_bible/` 空目录；有项目宪法模板 | 无世界模板库、无 `world_constitution.md` 初始文件、无世界 schema | 世界规则不可追踪，后续容易崩设定 | P0 |
| 人物 | 仅有设计 | `docs/09_novel_workspace.md`、V4 第 16 节、`docs/07_knowledge_compiler.md` | 无 | 人物机制和人物卡模板在文档中 | 无 `characters.md`、无人物卡模板文件、无动机链检查 | 主角欲望、反派逻辑容易漂移 | P0 |
| 大纲 | 仅有设计 | `docs/09_novel_workspace.md`、`docs/11_writing_pipeline.md`、V4 第 17 节 | 无 | 定义总纲、卷纲、连载计划 | 初始化脚本不生成 `book_outline.md`、`volume_001.md`、`serialization_plan.md` | 正文生产缺少上位结构 | P0 |
| 细纲 | 部分实现 | `docs/11_writing_pipeline.md`、V4 第 18 节 | `templates/chapter_plan.md`、`scripts/init_novel_project.py` | 有 Markdown 细纲模板，初始化生成 `ch001_plan.md` | 无 YAML schema、无批量生成、无 QG-4 检查 | 章节可能缺冲突、爽点、钩子仍进入正文 | P0 |
| 正文 | 尚未实现 | `docs/11_writing_pipeline.md`、V4 第 19 节 | `scripts/init_novel_project.py` 仅建目录 | 创建 `03_chapters/ch001/` 空目录 | 无正文模板、无 DeepSeek 输入协议、无版本流转脚本 | 容易跳过细纲和审稿直接写正文 | P1 |
| 审稿 | 部分实现 | `docs/12_review_system.md`、V4 第 20 节、`docs/ai-workflow/acceptance-criteria.md` | `templates/review_report.md`、初始化脚本生成 `final_review.md` | 有审稿维度和模板 | 无审稿执行入口、无评分聚合、无质量门禁测试 | 审稿闭环停留在人工文档 | P0 |
| 反馈 | 仅有设计 | `docs/13_feedback_control.md`、V4 第 21 节 | 初始化脚本创建 `05_feedback/` 空目录 | 反馈分类、分级、决策模板清晰 | 无评论导入、清洗、分类、采纳脚本 | 发布后反馈无法反哺后续创作 | P1 |
| 作文训练 | 仅有设计 | V4 第 27 节 | 无 | 定义训练范围和输出标准 | 无 `training/` 目录、无训练题模板 | 与主链路无直接影响，但能力未落地 | P2 |
| 图像 / 建筑提示词 | 尚未实现 | V4 第 9、31 节 | 无 | 建筑/城市作为学科用途被提及 | 无 `prompts/`、无建筑提示词模板 | 作为增强模块缺席，不影响主闭环 | P2 |
| 模型协作 | 部分实现 | `CLAUDE.md`、`AGENTS.md`、`docs/15_model_routing.md`、V4 第 8 节 | 无模型调用代码 | 角色分工、权限边界和任务模板已文档化 | 无 `.novelforge/model_routing.yaml`、无调用日志、无执行状态 | 依赖人工复制粘贴，流程不可复现 | P0 |
| 批处理 | 尚未实现 | V4 第 6、12、23 节 | 无 | 设计 `scripts/ingest/clean/chunk/extract/index/review/publish` | 当前只有 `check_docs_structure.py` 和 `init_novel_project.py` | 无法处理 5-10 本小说和多本书籍 | P0 |
| 数据存储 | 仅有设计 | V4 第 4、22 节、`pyproject.toml` | `pyproject.toml` 仅配置 V1 路径 | 文件制路径有初步配置 | 无 `data/`、`knowledge/`、`factory/`、SQLite、向量库、metadata | 数据源、版本、标签、引用关系缺失 | P0 |
| 检索 | 尚未实现 | V4 第 22 节 | 无 | 定义向量库与结构库职责 | 无索引脚本、无检索接口、无向量库配置 | 知识库规模扩大后不可用 | P2 |
| 质量评估 | 部分设计 | `docs/12_review_system.md`、V4 第 24 节 | `tests/test_structure.py` 只测文件存在 | 有审稿评分表和 QG-0 到 QG-5 概念 | 无自动质量门禁、无原创风险检测、无正文质量测试 | 生成质量依赖人工主观判断 | P0 |
| 版本管理 | 部分设计 | `docs/09_novel_workspace.md`、V4 第 28 节、`.gitignore` | Git 仓库存在 | 有 commit 规范和 final 保护规则 | 无 `PROJECT_STATE.md`、`CURRENT_GOAL.md`、`DECISIONS.md`、无 release package | 项目状态不可恢复，长期协作易断档 | P0 |

