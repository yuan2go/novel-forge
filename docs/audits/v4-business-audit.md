# V4 Business Audit

## 1. 项目当前定位

### 模块目标

本报告从产品业务负责人、技术架构审计者和小说工业化生产系统主编视角，审计 `novel-forge` 当前 V4 业务蓝图与仓库实际实现之间的差距。

### 输入

- `CLAUDE.md`
- `AGENTS.md`
- `README.md`
- `ROADMAP.md`
- `pyproject.toml`
- `Makefile`
- `docs/` 下 23 个 Markdown 文件
- `scripts/check_docs_structure.py`
- `scripts/init_novel_project.py`
- `tests/test_structure.py`
- `templates/` 下 7 个模板文件

### 输出

- V4 当前业务定位判断
- docs 文件总览
- 当前模块地图
- 当前业务流程图
- 已实现和未实现功能清单
- 风险点和优化项
- P0 / P1 / P2 路线图
- 下一阶段可执行任务列表

### 文件路径

`docs/audits/v4-business-audit.md`

### 执行流程

1. 读取项目级协作规则和根目录配置。
2. 逐篇读取 `docs/` 下所有 Markdown。
3. 核对脚本、模板和测试是否支撑文档中的 V4 能力。
4. 按业务链路、模块、数据结构、模型协作和风险进行审计。
5. 输出可供后续开发执行的优先级路线图。

### 验收标准

- 明确区分“已实现”“部分实现”“仅有设计”“尚未实现”。
- 每个重要判断引用具体路径作为证据。
- 不假设不存在的功能。
- 不修改业务代码。

### 风险与边界

本报告只做审计和规划，不直接重构目录、脚本、模板或业务数据。

## 2. 总体结论

当前仓库不是完整 V4 实现，而是“V1 文件项目制工程骨架 + V4 终局蓝图文档 + 初步 AI 协作规则”。V4 在 `docs/novel-forge-v4-final.md` 中定义了完整小说工业化系统，但实际代码只实现了基础结构校验和单本小说 workspace 初始化，尚未实现素材导入、清洗、拆解、知识库、题材库、世界观库、人物库、正文生产、审稿自动化、反馈分析、schema 校验、批处理 pipeline、检索或版本化数据管理。

当前最重要的矛盾是：文档已经进入 V4 业务复杂度，工程实现仍停留在 V1 骨架。下一步不应继续扩大愿景，而应先把 V4 最小可运行闭环压缩成可执行 pipeline。

## 3. docs 文件总览

| 文件 | 系统位置 | 审计判断 |
|---|---|---|
| `docs/00_overview.md` | 项目总览 | 定义小说工厂目标、核心链路和模型分工，属于顶层业务说明。 |
| `docs/01_architecture.md` | 总体架构 | 定义 L1-L5 五层架构，完整但多数层级尚未落地。 |
| `docs/02_global_assets.md` | 全局资产层 | 定义网文结构库、多学科知识库、反馈规律库和审稿规则库，目录尚未创建。 |
| `docs/03_world_lab.md` | 世界实验室 | 定义世界模板、共享世界、项目分支，目录尚未创建。 |
| `docs/04_project_incubation.md` | 项目孵化 | 定义创意访谈、候选生成、Gate、知识编译和 workspace 初始化，只有模板和初始化脚本部分支撑。 |
| `docs/05_reader_attraction_gate.md` | 读者吸引力 Gate | 评分维度和模板清晰，已有模板文件但无自动评分或任务入口。 |
| `docs/06_project_differentiation_gate.md` | 差异化 Gate | 定义项目矩阵和相似度判断，已有模板但无 `03_project_registry/` 和矩阵实现。 |
| `docs/07_knowledge_compiler.md` | 知识编译器 | 定义 project knowledge pack 结构，当前初始化脚本只创建空目录，不生成 pack 文件。 |
| `docs/08_project_constitution.md` | 项目宪法 | 模板和边界清晰，已有模板文件。 |
| `docs/09_novel_workspace.md` | 单本 workspace | 标准目录完整，但与 `scripts/init_novel_project.py` 生成结果不一致。 |
| `docs/10_claude_code_execution.md` | Claude Code 执行 | 定义任务卡、接管报告和模式，当前只有模板与部分初始化文件支撑。 |
| `docs/11_writing_pipeline.md` | 写作生产线 | 定义细纲、v0/v1/v2/final、章节商业单元，尚无生产脚本。 |
| `docs/12_review_system.md` | 审稿系统 | 评分体系清晰，只有 `templates/review_report.md`，无审稿执行入口。 |
| `docs/13_feedback_control.md` | 反馈控制 | 反馈分类、分级、采纳逻辑完整，尚无评论导入、聚合和决策脚本。 |
| `docs/14_multi_project_scheduler.md` | 多项目调度 | 定义 registry 和日报，只有 `templates/project_registry.md`，无目录和调度脚本。 |
| `docs/15_model_routing.md` | 模型路由 | 定义 `.novelforge/model_routing.yaml`，该配置尚不存在。 |
| `docs/16_risk_control.md` | 风险控制 | 原创、同质化、剧情失控、设定过重风险清晰，缺自动化检查。 |
| `docs/17_mvp_roadmap.md` | MVP 路线 | V1 闭环定义清楚，但当前仅完成工程骨架的一部分。 |
| `docs/18_templates.md` | 模板集合 | 文档模板集合与 `templates/` 部分一致，但 V4 YAML schema 模板未落地。 |
| `docs/ai-workflow/README.md` | AI 协作流程 | 定义任务协作规则和验收入口，已落地为文档。 |
| `docs/ai-workflow/codex-task-template.md` | Codex 任务模板 | 可用于工程任务，但未接入检查脚本。 |
| `docs/ai-workflow/acceptance-criteria.md` | 验收标准 | 定义验收结论和标准，未接入自动检查。 |
| `docs/novel-forge-v4-final.md` | V4 总蓝图 | 定义完整 V4 工业系统，是当前最超前文档，实际实现严重不足。 |

## 4. 当前模块地图

```text
业务目标
  ├── 热门小说拆解：仅有 V4 设计
  ├── 专业书籍解析：仅有 V4 设计
  ├── 多学科知识库：仅有 V1/V4 设计
  ├── 素材库：仅有 V4 设计
  ├── 题材库：仅有 V4 设计
  ├── 世界观：有设计和 workspace 目录骨架
  ├── 人物：有设计，workspace 标准需要 characters.md，但脚本未生成
  ├── 大纲：有设计和 chapter_plans 目录骨架
  ├── 细纲：有模板和初始化样例
  ├── 正文：有目录骨架但无生成脚本和模板
  ├── 审稿：有模板和初始化样例
  ├── 反馈：有目录骨架但无导入/分析脚本
  ├── 训练题：仅有 V4 设计
  ├── 图像/建筑提示词：仅有 V4 学科与扩展方向提示，未实现
  ├── AI 多模型协作：文档已建立，未形成自动调度
  └── 工程校验：部分实现
```

## 5. 当前业务流程图

### V4 目标链路

```text
导入热门小说 / 专业书籍 / 评论反馈
  ↓
清洗文本
  ↓
章节切分 / chunk
  ↓
DeepSeek 粗拆解
  ↓
Codex 结构化整理
  ↓
ChatGPT 高级分析
  ↓
原创风险过滤
  ↓
写入 knowledge / factory
  ↓
生成题材卡
  ↓
生成世界观
  ↓
生成人物系统
  ↓
生成总纲 / 卷纲 / 前 30 章细纲
  ↓
DeepSeek 正文初稿
  ↓
ChatGPT/Codex 审稿
  ↓
修订
  ↓
发布准备
  ↓
评论反馈导入
  ↓
反馈反哺后续细纲
```

### 当前实际链路

```text
手工创意或模板
  ↓
手工填写 Gate / 宪法模板
  ↓
可运行脚本初始化 04_novel_projects/{project_id}
  ↓
生成部分 workspace 目录和少量模板文件
  ↓
人工或 AI 手工继续执行
```

当前链路在“导入、清洗、拆解、知识沉淀、题材生成、世界观生成、人物生成、正文生成、审稿执行、反馈导入”处均未自动打通。

## 6. 已实现功能清单

| 功能 | 状态 | 证据 |
|---|---|---|
| 项目顶层说明 | 已实现 | `README.md` |
| Agent 协作规则 | 部分实现 | `AGENTS.md`、`CLAUDE.md` |
| V1 架构文档 | 已实现 | `docs/00_overview.md` 到 `docs/18_templates.md` |
| V4 总蓝图 | 已实现为文档 | `docs/novel-forge-v4-final.md` |
| AI workflow 文档 | 已实现为文档 | `docs/ai-workflow/` |
| 核心 Markdown 模板 | 部分实现 | `templates/*.md` |
| 结构校验脚本 | 部分实现 | `scripts/check_docs_structure.py` |
| 单本 workspace 初始化脚本 | 部分实现 | `scripts/init_novel_project.py` |
| 基础测试 | 部分实现 | `tests/test_structure.py` |
| Makefile 命令 | 部分实现 | `Makefile` |
| 项目级任务骨架 | 部分实现 | `tasks/README.md`、`tasks/backlog.md`、`tasks/task-template.md` |

## 7. 未实现 / 部分实现功能清单

| 功能 | 当前状态 | 证据与说明 |
|---|---|---|
| 热门小说拆解 | 仅有设计 | `docs/novel-forge-v4-final.md` 第 12 节定义流程，未见 `data/`、`knowledge/dissections/`、拆解脚本。 |
| 专业书籍解析 | 仅有设计 | V4 第 13 节定义，未见 `knowledge/dissections/professional_books/` 或解析入口。 |
| 多学科知识库 | 仅有设计 | `docs/02_global_assets.md`、V4 第 9 节定义，未落地目录和 schema。 |
| 素材库 | 尚未实现 | V4 要求 `data/raw/`、`data/cleaned/`，仓库无这些目录。 |
| 题材库 | 仅有设计 | V4 第 14 节定义 `factory/topics/`，仓库无 `factory/`。 |
| 世界观库 | 部分设计 | `docs/03_world_lab.md` 和 V4 第 15 节完整，但仓库无 `01_world_lab/` 或 `factory/worlds/`。 |
| 人物系统 | 仅有设计 | V4 第 16 节定义人物卡，现有初始化脚本不生成 `characters.md`。 |
| 大纲系统 | 仅有设计 | `docs/09_novel_workspace.md` 设计 `book_outline.md`、`volume_001.md`，脚本只生成 `ch001_plan.md`。 |
| 细纲系统 | 部分实现 | `templates/chapter_plan.md` 和初始化样例存在，但无批量生成或校验。 |
| 正文生产 | 尚未实现 | 只有 `03_chapters/ch001/` 目录骨架，无正文模板、生成脚本或模型调用接口。 |
| 审稿 | 部分实现 | `templates/review_report.md` 存在，无自动审稿入口、评分汇总或质量门禁。 |
| 反馈 | 仅有设计 | `docs/13_feedback_control.md` 完整，脚本未实现评论导入、分类、决策。 |
| 训练题 | 仅有设计 | V4 第 27 节定义，仓库无 `training/`。 |
| 图像 / 建筑提示词 | 尚未实现 | V4 提到建筑/城市学科和扩展方向，无 prompts 或模板。 |
| 模型协作 | 部分实现 | 文档定义清晰，但无 `.novelforge/model_routing.yaml`、调用协议或日志。 |
| 批处理 | 尚未实现 | V4 要求 `scripts/ingest/clean/chunk/extract/index/review/publish`，当前只有两个脚本。 |
| 数据存储 | 仅有设计 | V4 提到 Markdown/JSON/YAML/SQLite/MySQL/向量库，当前无 schema、DB 或索引。 |
| 检索 | 尚未实现 | V4 定义向量库作用，当前未实现。 |
| 质量评估 | 部分设计 | 审稿维度和验收标准清晰，未自动化。 |
| 版本管理 | 部分设计 | Git 规则在文档中，缺 `PROJECT_STATE.md`、`CURRENT_GOAL.md`、`DECISIONS.md`。 |

## 8. 数据结构与目录结构审计

### 当前清晰之处

- `templates/` 与 V1 文档基本一致，能支撑手工填写 Gate、宪法、细纲、审稿。
- `scripts/init_novel_project.py` 使用 `04_novel_projects/`，与 `pyproject.toml` 的 `workspace_dir` 一致。
- `.gitignore` 已保护 `.env` 和部分 runtime/cache/snapshots 文件。

### 当前混乱或冲突

- V1 文档使用 `00_global_assets/`、`01_world_lab/`、`03_project_registry/`、`04_novel_projects/`，V4 文档改为 `data/`、`knowledge/`、`factory/`、`manuscripts/`、`reviews/`、`feedback/`，两套目录体系并存。
- `docs/09_novel_workspace.md` 的标准 workspace 比 `scripts/init_novel_project.py` 生成结果更完整，脚本缺少 `01_bible/world_constitution.md`、`01_bible/characters.md`、`02_outline/book_outline.md`、`02_outline/serialization_plan.md`、`07_style/style_guide.md`、`08_tasks/current_sprint.md` 等关键文件。
- V4 要求 `PROJECT_STATE.md`、`CURRENT_GOAL.md`、`DECISIONS.md`，当前不存在。
- V4 要求 `schemas/` 和 JSON/YAML schema，当前不存在。
- V4 要求 `configs/models.yaml`、`configs/pipeline.yaml`、`configs/review_rules.yaml`，当前不存在。
- `ROADMAP.md` 仍声明“当前只推进 V1”，但已有 V4 总文档，版本状态不一致。

### 数据污染风险

当前缺少以下边界，会导致长期生产时数据污染：

- 原始素材与抽象拆解未分离。
- 热门小说拆解与多学科知识卡未分离。
- 项目私有知识包与全局知识库未分离。
- 正文草稿、修订稿、终稿、发布稿未形成统一版本路径。
- 读者反馈原文、清洗结果、聚合结论、采纳决策未分层。
- 缺少 source、license、abstraction_level、forbidden_usage、copy_risk 等元数据必填规则。

## 9. 模型协作机制审计

### 职责清晰处

- `docs/15_model_routing.md`、`AGENTS.md`、`CLAUDE.md` 和 V4 第 8 节都明确了 Claude Code、Codex、DeepSeek、ChatGPT 的分工。
- DeepSeek 被限定为初稿、批量、粗分类，不能做最终审稿和 final。
- ChatGPT/Codex 被定位为高质量判断和审稿。
- Claude Code 被定位为总控、文件治理、任务执行和状态维护。

### 落地不足

- 没有模型路由配置文件。
- 没有任务执行日志或模型调用记录。
- 没有标准 task packet 目录和状态机。
- 没有“DeepSeek 输出 → ChatGPT 审稿 → Claude Code 修订 → 主编确认”的可执行脚本或文件协议。
- 当前流程仍高度依赖人工复制粘贴。

## 10. 风险点清单

### 业务风险

- V4 业务蓝图过大，当前主链路没有打通。
- 热门小说拆解只能停留在文档，无法沉淀为可生产资产。
- 多学科知识库、网文拆解库、素材库的边界尚未工程化。
- 正文生产没有自动审稿闭环。
- 读者反馈无法导入、分类、聚合、采纳和回写。

### 技术风险

- V1 和 V4 目录体系冲突。
- 缺 schema，所有 YAML/JSON 结构仅存在于文档示例中。
- 缺批处理入口，无法运行导入、清洗、切分、拆解、索引、审稿 pipeline。
- 缺任务状态管理和日志。
- `init_novel_project.py --force` 会删除已有项目目录，且无 dry-run。

### 创作质量风险

- 容易生成空泛设定，因为题材、人物、世界观、细纲门禁没有自动检查。
- 缺人物动机链、因果链、伏笔回收、爽点密度、章节钩子、风格一致性检查器。
- 审稿报告模板存在，但没有强制每章通过审稿再进入 final。

### 法务与合规风险

- V4 强调“不照抄，只抽象”，但没有可执行的素材来源、抽象等级和 forbidden_usage schema。
- 原始文本存储、拆解结果、生成内容之间缺少边界定义。
- 缺版权来源记录和拆解结果的引用追踪。

## 11. 优化项清单

### P0：必须先做

1. 统一 V4 最小目录结构，明确 V1 `04_novel_projects/` 与 V4 `data/knowledge/factory/manuscripts` 的关系。
2. 新增 `PROJECT_STATE.md`、`CURRENT_GOAL.md`、`DECISIONS.md`，让项目状态可追踪。
3. 建立核心 schema：material、dissection、discipline_card、topic、world、character、outline、chapter_plan、review、feedback。
4. 补齐 `scripts/init_novel_project.py` 与 `docs/09_novel_workspace.md` 的差距，并增加 `--dry-run`。
5. 建立最小 pipeline：导入样例素材 → 清洗 → 生成拆解报告占位 → 生成题材卡 → 初始化项目。
6. 将质量门禁拆成可检查清单：QG-0 原创、QG-1 题材、QG-2 世界观、QG-3 人物、QG-4 细纲、QG-5 正文。

### P1：重要优化

1. 建立素材库标签系统和来源元数据。
2. 建立热门小说拆解模板和测试样例。
3. 建立多学科知识卡模板和专业书籍解析流程。
4. 建立读者反馈导入、清洗、分类和采纳决策模板。
5. 建立任务队列和状态管理。
6. 建立审稿评分汇总和质量看板。

### P2：增强能力

1. 建立修辞、微表情、动作、场景、建筑提示词库。
2. 建立作文训练和阅读训练模块。
3. 建立多模型评分对比机制。
4. 建立悬疑逻辑校验器和伏笔回收检查器。
5. 建立章节追读预测和角色人气预测的轻量指标。

## 12. P0 / P1 / P2 优先级路线图

### P0 路线图

| 顺序 | 任务 | 产物 |
|---:|---|---|
| 1 | 冻结 V4 最小目录与数据对象 | `docs/architecture/v4-minimum-structure.md` 或更新 V4 文档 |
| 2 | 补项目状态文件 | `PROJECT_STATE.md`、`CURRENT_GOAL.md`、`DECISIONS.md` |
| 3 | 建立 schema 目录和前 5 个核心 schema | `schemas/*.schema.json` |
| 4 | 增加 `--dry-run` 和 workspace 完整性测试 | `scripts/init_novel_project.py`、`tests/` |
| 5 | 增加最小素材导入与清洗脚本 | `scripts/ingest/`、`scripts/clean/` |
| 6 | 增加质量门禁文档和检查清单 | `docs/quality-gates/` 或 `templates/quality_gate.md` |

### P1 路线图

| 顺序 | 任务 | 产物 |
|---:|---|---|
| 1 | 热门小说拆解模板落地 | `templates/novel_dissection_template.md` |
| 2 | 专业知识卡模板落地 | `templates/discipline_card_template.md` |
| 3 | 题材卡、世界观卡、人物卡模板落地 | `templates/*_template.md` |
| 4 | 批处理状态与日志规范 | `logs/`、`output/reports/`、任务状态文件 |
| 5 | 反馈分析模板和样例 | `templates/feedback_report_template.md` |

### P2 路线图

| 顺序 | 任务 | 产物 |
|---:|---|---|
| 1 | 建立语言与风格资产库 | `knowledge/discipline/language_rhetoric/` |
| 2 | 建立建筑 / 城市提示词库 | `prompts/shared/architecture_city/` |
| 3 | 建立作文训练任务模板 | `training/composition/` |
| 4 | 多模型评分对比 | `reviews/final_reports/model_comparison.md` |

## 13. 下一阶段建议任务列表

1. 新增 `PROJECT_STATE.md`、`CURRENT_GOAL.md`、`DECISIONS.md`，先解决状态不可追踪。
2. 输出 V4 最小目录冻结报告，决定是否保留 V1 编号目录或迁移到 V4 语义目录。
3. 新增 `schemas/` 前 5 个 schema，并用测试验证 JSON 样例。
4. 为 `init_novel_project.py` 增加 `--dry-run`，并补 workspace 结构完整性测试。
5. 新增素材导入、清洗、拆解报告占位的最小脚本，但不引入外部依赖。
6. 新增质量门禁模板，先用 Markdown checklist 落地 QG-0 到 QG-5。

