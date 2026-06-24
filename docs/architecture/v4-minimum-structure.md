# V4 Minimum Structure

## 1. 模块目标

冻结 `novel-forge` 从 V1 文件项目制过渡到 V4 小说工业化系统时的最小目录策略，明确 V1 目录与 V4 目录的兼容关系。

本文件不执行大规模迁移，只定义后续开发应遵守的目录边界。

## 2. 输入

- `README.md`
- `ROADMAP.md`
- `pyproject.toml`
- `docs/09_novel_workspace.md`
- `docs/novel-forge-v4-final.md`
- `docs/audits/v4-business-audit.md`
- `docs/audits/v4-module-matrix.md`
- `docs/audits/v4-risk-register.md`
- `scripts/init_novel_project.py`

## 3. 输出

- V1 与 V4 目录关系
- 当前必须存在的最小目录
- 延后创建的 V4 目录
- 数据对象归属规则
- 迁移边界和验收标准

## 4. 文件路径

```text
docs/architecture/v4-minimum-structure.md
```

## 5. 执行流程

1. 保留当前 V1 工作区目录，不做破坏性迁移。
2. 将 V4 目录分为“立即落地”“按 pipeline 落地”“暂缓落地”。
3. 先补 schema 和状态文件，再补导入、清洗、拆解、审稿等 pipeline。
4. 后续每新增一个 V4 目录，必须同时说明输入、输出、数据边界和验收标准。

## 6. 当前目录策略

### 6.1 保留的 V1 目录

| 目录 | 当前定位 | V4 兼容策略 |
|---|---|---|
| `docs/` | 架构、流程、审计和规则文档 | 保留，继续作为系统设计与审计主目录。 |
| `templates/` | Markdown 模板库 | 保留，逐步补 V4 task packet、dissection、topic、review 等模板。 |
| `scripts/` | 标准库脚本 | 保留，后续按 `ingest/clean/extract/validate` 子目录扩展。 |
| `tests/` | 标准库测试 | 保留，逐步覆盖 schema、初始化脚本和质量门禁。 |
| `tasks/` | 项目级任务系统 | 保留，用于工程和 AI 协作任务，不替代单本 workspace 的 `08_tasks/`。 |
| `04_novel_projects/` | 单本小说 workspace 默认目录 | 保留，继续作为 V1/V4 过渡期的单项目生产区。 |

### 6.2 立即落地的 V4 目录

| 目录 | 用途 | 创建条件 |
|---|---|---|
| `schemas/` | 存放核心数据对象 JSON schema | 已开始落地第一批核心 schema。 |
| `docs/architecture/` | 存放目录、架构和迁移决策 | 已用于保存本文件。 |
| `docs/audits/` | 存放审计报告和风险登记 | 已生成 V4 审计文件。 |

### 6.3 按 pipeline 落地的 V4 目录

以下目录只在对应功能开始实现时创建，不提前空置整棵树。

| 目录 | 对应 pipeline | 最小创建条件 |
|---|---|---|
| `data/` | 素材导入、清洗、切分 | 实现 material schema 和导入样例后创建。 |
| `knowledge/` | 拆解结果、多学科知识卡、商业结构卡 | 实现 dissection 或 discipline_card schema 后创建。 |
| `factory/` | 题材、世界观、人物、大纲、细纲资产 | 实现 topic/world/character/outline schema 后创建。 |
| `manuscripts/` | 正文草稿、修订稿、终稿、发布稿 | 正文生产 pipeline 开始后创建。 |
| `reviews/` | 审稿报告汇总 | 审稿 pipeline 开始后创建。 |
| `feedback/` | 评论导入、清洗、分类、采纳建议 | 反馈 pipeline 开始后创建。 |
| `prompts/` | 多模型提示词库 | 模型路由配置落地后创建。 |
| `output/` | 报告、导出、发布包 | 有导出或报告脚本后创建。 |
| `configs/` | 模型、pipeline、审稿规则配置 | 配置进入可执行流程后创建。 |

### 6.4 暂缓落地的 V4 能力

| 能力 | 暂缓原因 |
|---|---|
| SQLite / MySQL | 当前仍以文件为唯一事实源。 |
| 向量数据库 | 当前尚无可索引知识库和检索脚本。 |
| Web 管理台 | 当前主链路未闭环，管理台会提前增加复杂度。 |
| Redis / Celery | 当前没有稳定批处理任务队列需求。 |
| 完整多 Agent 平台 | 当前由文件任务卡和人工调度维持。 |

## 7. V1 与 V4 数据对象映射

| V4 对象 | V4 目标路径 | 当前过渡路径 | 说明 |
|---|---|---|---|
| 素材 | `data/raw/` | 暂无 | 后续只存合法来源元数据和允许保存的原始输入。 |
| 清洗文本 | `data/cleaned/` | 暂无 | 清洗脚本落地后创建。 |
| 拆解结果 | `knowledge/dissections/` | 暂无 | 必须只存抽象结构，不存可仿写桥段。 |
| 多学科知识 | `knowledge/discipline/` | 暂无 | 必须通过 knowledge compiler 才能进入项目。 |
| 题材卡 | `factory/topics/` | 暂无 | 可由拆解和知识卡生成。 |
| 世界观 | `factory/worlds/` 或 workspace `01_bible/` | `04_novel_projects/{project_id}/01_bible/` | 全局世界资产和项目私有世界需分离。 |
| 人物 | `factory/characters/` 或 workspace `01_bible/characters.md` | 未来补齐 workspace 文件 | 人物卡需要保持项目私有版本。 |
| 大纲 | `factory/outlines/` 或 workspace `02_outline/` | `04_novel_projects/{project_id}/02_outline/` | 单本项目以 workspace 为真相源。 |
| 细纲 | `factory/chapter_plans/` 或 workspace `02_outline/chapter_plans/` | `04_novel_projects/{project_id}/02_outline/chapter_plans/` | 当前已有 chapter plan 模板。 |
| 正文 | `manuscripts/` 或 workspace `03_chapters/` | `04_novel_projects/{project_id}/03_chapters/` | 过渡期以 workspace 保存正文版本。 |
| 审稿 | `reviews/` 或 workspace `04_reviews/` | `04_novel_projects/{project_id}/04_reviews/` | 全局汇总后续再建。 |
| 反馈 | `feedback/` 或 workspace `05_feedback/` | `04_novel_projects/{project_id}/05_feedback/` | 项目私有反馈优先。 |
| 训练题 | `training/` | 暂无 | P2 能力，暂缓。 |

## 8. 数据边界

- 原始素材不得直接进入正文生成 prompt。
- 热门小说拆解只保存抽象结构、节奏、爽点、毒点和禁用元素。
- 多学科知识不得直接进入正文，必须通过项目知识包转译。
- 单本小说的项目宪法、正文、审稿和反馈以 `04_novel_projects/{project_id}/` 为真相源。
- 全局资产只能保存可复用抽象规则，不保存具体桥段、台词、独特角色关系或可识别设定。

## 9. 迁移规则

短期：

- 不迁移已有 `docs/`、`templates/`、`scripts/`、`tests/`。
- 不创建完整空 V4 目录树。
- 先补 `schemas/` 和状态文件。

中期：

- 当素材导入脚本落地时创建 `data/`。
- 当拆解 schema 与模板落地时创建 `knowledge/`。
- 当题材、世界观、人物 schema 落地时创建 `factory/`。

长期：

- 当文件制 pipeline 稳定后，再评估 SQLite、向量库和 Web 管理台。

## 10. 验收标准

- 新增目录必须有明确业务对象和输入输出。
- 新增目录不能只是为了匹配 V4 蓝图而空置。
- V1 workspace 继续可用。
- schema 先于批处理脚本落地。
- 批处理脚本先于数据库或向量库落地。
- 单本小说项目文件不与全局知识库混写。

## 11. 风险与边界

- 本文件不替代 `docs/novel-forge-v4-final.md`，只定义最小落地策略。
- 本文件不授权删除、重命名或迁移现有核心目录。
- 如果后续决定迁移目录，必须先输出迁移报告和回滚方案。
