# V4 Risk Register

## 1. 模块目标

登记 V4 当前业务、技术、数据、创作质量、合规和工作流风险，为后续 P0/P1/P2 开发排序提供依据。

## 2. 输入

- `docs/novel-forge-v4-final.md`
- `docs/00_overview.md` 到 `docs/18_templates.md`
- `CLAUDE.md`
- `AGENTS.md`
- `scripts/`
- `templates/`
- `tests/`

## 3. 输出

V4 风险登记表。

## 4. 文件路径

`docs/audits/v4-risk-register.md`

## 5. 执行流程

1. 按风险类型归类。
2. 对照文档目标和实际实现找证据。
3. 标注严重程度、概率和修复建议。
4. 给出优先级。

## 6. 验收标准

- 覆盖业务、技术、数据、创作质量、合规、工作流风险。
- 每项风险有证据路径。
- 修复建议可执行。

## 7. 风险与边界

本登记表不替代具体整改任务卡。

| 风险编号 | 风险类型 | 风险描述 | 影响范围 | 严重程度 | 发生概率 | 证据 | 修复建议 | 优先级 |
|---|---|---|---|---|---|---|---|---|
| R-001 | 业务风险 | V4 蓝图完整，但主链路没有可运行闭环 | 全项目 | 高 | 高 | V4 第 29 节定义最小闭环；当前只有两个脚本 | 先实现最小 pipeline：素材样例、清洗、拆解占位、题材卡、workspace 初始化 | P0 |
| R-002 | 业务风险 | 热门小说拆解无法转化为可生产资产 | 拆解库、题材库、合规 | 高 | 高 | V4 第 12 节；无 `knowledge/dissections/` | 建立拆解模板、schema、样例和原创风险字段 | P0 |
| R-003 | 业务风险 | 多学科知识无法进入项目知识包 | 知识编译、世界观、人物 | 高 | 中 | `docs/07_knowledge_compiler.md` 定义 pack；脚本只建空目录 | 补 `project_knowledge_pack` 模板文件和 discipline card schema | P0 |
| R-004 | 业务风险 | 正文生产缺少审稿闭环 | 正文质量、发布风险 | 高 | 高 | `docs/11_writing_pipeline.md`、`docs/12_review_system.md`；无生成/审稿脚本 | 建立章节任务包、审稿任务包和 final 保护检查 | P0 |
| R-005 | 业务风险 | 读者反馈无法反哺后续创作 | 连载迭代 | 中 | 高 | `docs/13_feedback_control.md`；无反馈导入脚本 | 建立 `feedback/raw_comments` 样例、分类模板和决策报告流程 | P1 |
| R-006 | 技术风险 | V1 与 V4 目录体系并存且未声明映射关系 | 架构、脚本、测试 | 高 | 高 | V1 使用 `04_novel_projects/`；V4 使用 `data/knowledge/factory/manuscripts` | 输出目录冻结决策，明确兼容层或迁移路线 | P0 |
| R-007 | 技术风险 | 缺少统一 schema，结构化数据无法校验 | 数据质量、批处理 | 高 | 高 | V4 第 6 节列出 `schemas/`；仓库无 `schemas/` | 新增核心 JSON schema 和示例测试 | P0 |
| R-008 | 技术风险 | 缺少批处理入口 | 素材导入、拆解、清洗 | 高 | 高 | V4 要求 `scripts/ingest/clean/chunk/extract`；当前只有两个脚本 | 新增标准库脚本目录和最小 CLI | P0 |
| R-009 | 技术风险 | `init_novel_project.py --force` 可删除已有项目 | 单本项目数据 | 高 | 中 | 脚本中 `shutil.rmtree(project_root)` | 增加 `--dry-run`、交互外安全提示、备份或拒绝非空目录策略 | P0 |
| R-010 | 技术风险 | 测试只覆盖文件存在性 | 回归控制 | 中 | 高 | `tests/test_structure.py` 仅检查根文件、目录、模板存在 | 增加 schema、模板字段、workspace 初始化、dry-run 测试 | P0 |
| R-011 | 数据风险 | 原始素材、清洗文本、拆解结果未分层 | 版权、可追溯、数据污染 | 高 | 高 | V4 第 4 节要求 `data/raw/cleaned/chunks/metadata`；目录缺失 | 建立 `data/` 分层和 metadata schema | P0 |
| R-012 | 数据风险 | 缺少来源、授权、抽象等级、禁用范围字段 | 合规、原创风险 | 高 | 高 | `docs/02_global_assets.md` 要求来源、抽象程度、禁用范围；无 schema | 所有素材和知识卡强制 source/license/abstraction/forbidden_usage | P0 |
| R-013 | 数据风险 | 缺少项目级状态文件 | 长期协作、恢复能力 | 高 | 高 | V4 第 28 节要求 `PROJECT_STATE.md`、`CURRENT_GOAL.md`；当前缺失 | 新增状态文件并纳入检查脚本 | P0 |
| R-014 | 数据风险 | 缺少版本和引用关系 | 审稿、反馈、追溯 | 中 | 高 | V4 第 22、28 节；无版本 schema | 为 manuscript/review/feedback 加 source_file、target_file、version 字段 | P1 |
| R-015 | 创作质量风险 | 人物动机链没有强制检查 | 人物可信度、主线稳定 | 高 | 中 | V4 第 16 节；无人物卡文件和检查器 | 建人物卡模板、动机链 checklist、审稿项 | P0 |
| R-016 | 创作质量风险 | 因果链和伏笔回收缺少检查 | 悬疑、长线逻辑 | 高 | 中 | `docs/11_writing_pipeline.md`、V4 第 11、18 节 | 建 `unresolved_foreshadowing` 与 chapter_plan 校验项 | P1 |
| R-017 | 创作质量风险 | 爽点密度和章节钩子标准未自动门禁 | 商业追读 | 高 | 高 | `docs/05_reader_attraction_gate.md`、`docs/11_writing_pipeline.md` | 实现 QG-4/QG-5 Markdown checklist 和测试样例 | P0 |
| R-018 | 创作质量风险 | 风格一致性缺少文件支撑 | 正文质量 | 中 | 中 | `docs/09_novel_workspace.md` 要求 `07_style/` 文件；脚本只建空目录 | 初始化生成 `style_guide.md`、`dialogue_rules.md`、`forbidden_ai_tone.md` | P1 |
| R-019 | 合规风险 | “拆解热门小说”缺少可执行版权边界 | 法务、声誉 | 高 | 中 | V4 第 3、12、24 节强调不照抄；无 policy 文件和 schema | 新增 originality policy、素材来源记录和 QG-0 检查 | P0 |
| R-020 | 合规风险 | 原始文本与生成内容边界不清 | 数据污染、侵权 | 高 | 中 | V4 要求 `data/raw` 和 `knowledge/dissections` 分离；当前未落地 | 禁止原文进入生成 prompt，拆解结果必须只存抽象结构 | P0 |
| R-021 | 工作流风险 | 模型协作依赖人工复制粘贴 | 稳定性、可复现 | 中 | 高 | `docs/15_model_routing.md` 定义路由，`.novelforge/model_routing.yaml` 不存在 | 建模型路由配置、任务包字段和调用记录模板 | P1 |
| R-022 | 工作流风险 | 任务卡系统存在但未纳入校验 | 执行越界 | 中 | 高 | `tasks/` 存在；`check_docs_structure.py` 未检查 | 扩展结构检查覆盖 `tasks/`、AI workflow 和任务字段 | P0 |
| R-023 | 工作流风险 | 质量门禁只在 V4 文档中，未进入执行流程 | 发布质量 | 高 | 高 | V4 第 24 节；无质量门禁模板或脚本 | 建 `templates/quality_gate.md` 和 `scripts/validate_quality_gate.py` | P0 |
| R-024 | 工作流风险 | ROADMAP 与 V4 状态不一致 | 项目管理 | 中 | 高 | `ROADMAP.md` 声明当前只推进 V1；V4 文档存在 | 更新状态文件，不必立即改路线，但要明确 V4 是蓝图还是当前目标 | P0 |

