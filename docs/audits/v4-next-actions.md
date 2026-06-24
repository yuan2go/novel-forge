# V4 Next Actions

## 1. 模块目标

将 V4 审计结论转化为下一步 Claude Code 可执行任务清单。

## 2. 输入

- `docs/audits/v4-business-audit.md`
- `docs/audits/v4-module-matrix.md`
- `docs/audits/v4-risk-register.md`
- 当前仓库结构和 V4 文档

## 3. 输出

下一步任务表。

## 4. 文件路径

`docs/audits/v4-next-actions.md`

## 5. 执行流程

1. 优先列 P0 主链路任务。
2. 每个任务必须能交给 Claude Code 或 Codex 执行。
3. 每个任务必须有涉及文件和验收标准。
4. 不纳入空泛建议。

## 6. 验收标准

- 每项任务可独立执行。
- 每项任务有明确目标、文件范围和验收标准。
- P0 任务优先修复闭环、schema、目录、质量门禁和状态管理。

## 7. 风险与边界

执行这些任务前仍需逐项创建任务卡，不应一次性大规模重构。

| 序号 | 任务 | 目标 | 涉及文件 | 验收标准 | 优先级 |
|---:|---|---|---|---|---|
| 1 | 新增项目状态三件套 | 让 V4 当前阶段、唯一目标和决策记录可追踪 | `PROJECT_STATE.md`、`CURRENT_GOAL.md`、`DECISIONS.md`、可选更新 `scripts/check_docs_structure.py` | 三个文件存在；包含当前阶段、目标、风险、下一步；`make check` 不受影响 | P0 |
| 2 | 输出 V4 最小目录冻结文档 | 解决 V1 编号目录和 V4 语义目录冲突 | `docs/architecture/v4-minimum-structure.md` 或 `docs/audits/v4-directory-decision.md` | 明确 `04_novel_projects/`、`data/`、`knowledge/`、`factory/`、`manuscripts/` 的关系；列出暂不创建的大目录 | P0 |
| 3 | 新增核心 schema 第一批 | 让素材、拆解、题材、章节细纲、审稿可校验 | `schemas/material.schema.json`、`schemas/dissection.schema.json`、`schemas/topic.schema.json`、`schemas/chapter_plan.schema.json`、`schemas/review.schema.json`、`tests/` | schema 文件存在；至少有一个测试验证 schema 文件为合法 JSON；不引入外部依赖 | P0 |
| 4 | 为 workspace 初始化增加 `--dry-run` | 避免脚本写入和 `--force` 删除风险 | `scripts/init_novel_project.py`、`tests/test_init_novel_project.py` | `--dry-run` 不创建目录；普通初始化仍可用；`make test` 通过 | P0 |
| 5 | 对齐 workspace 标准结构 | 让初始化结果满足 `docs/09_novel_workspace.md` 的最低接管条件 | `scripts/init_novel_project.py`、`templates/`、`tests/` | 初始化项目包含 `world_constitution.md`、`characters.md`、`serialization_plan.md`、`current_sprint.md`、style 文件；测试覆盖 | P0 |
| 6 | 建立质量门禁模板 | 将 QG-0 到 QG-5 从 V4 文档落成可用检查清单 | `templates/quality_gate.md`、`docs/quality-gates/README.md` 或 `docs/audits/quality-gate-plan.md` | 模板覆盖原创、题材、世界观、人物、细纲、正文；每个门禁有通过/退回标准 | P0 |
| 7 | 扩展结构检查脚本 | 让新增 V4 工程骨架进入 `make check` | `scripts/check_docs_structure.py`、`tests/test_structure.py` | 检查 `CLAUDE.md`、`docs/ai-workflow/`、`tasks/`、`docs/audits/`、可选 `schemas/`；失败提示清晰 | P0 |
| 8 | 建立素材导入最小目录与样例 metadata | 为后续热门小说/书籍拆解提供数据入口 | `data/README.md`、`data/raw/README.md`、`data/metadata/material_sample.json`、`schemas/material.schema.json` | 不放入真实版权文本；样例只描述元数据；schema 校验测试通过 | P0 |
| 9 | 新增热门小说拆解模板 | 把“不照抄，只抽象”落到报告格式 | `templates/novel_dissection_template.md`、`schemas/dissection.schema.json` | 模板包含结构、节奏、爽点、毒点、可复用抽象、禁止模仿、copy_risk | P1 |
| 10 | 新增多学科知识卡模板 | 支撑专业书籍解析进入小说生产 | `templates/discipline_card_template.md`、`schemas/discipline_card.schema.json` | 模板包含 source、core_concept、story_function、genre_usage、avoid | P1 |
| 11 | 新增题材卡、世界观卡、人物卡模板 | 让拆解资产能转化为创作资产 | `templates/topic_card_template.md`、`templates/worldview_template.md`、`templates/character_card_template.md` | 三个模板字段覆盖 V4 第 14-16 节关键结构 | P1 |
| 12 | 建立反馈报告模板 | 为发布后反馈反哺预留稳定格式 | `templates/feedback_report_template.md`、`schemas/feedback.schema.json` | 模板包含评论来源、分类、频次、采纳建议、影响章节、项目宪法检查 | P1 |
| 13 | 建立模型路由配置草案 | 减少人工选择模型的不一致 | `.novelforge/model_routing.yaml`、`docs/15_model_routing.md` | 配置覆盖 Gate、拆解、正文、审稿、反馈；不包含真实 API Key | P1 |
| 14 | 建立审稿评分汇总模板 | 让章节质量可复盘 | `reviews/README.md` 或 `templates/review_summary_template.md` | 能汇总结构、节奏、爽点、人物、世界观、原创性评分 | P1 |
| 15 | 建立作文训练目录骨架 | 落地非主链路训练模块 | `training/README.md`、`training/composition/README.md` | 明确训练题不进入正式正文；包含输入、输出和验收标准 | P2 |
| 16 | 建立建筑/城市提示词目录骨架 | 支撑图像和场景资产扩展 | `prompts/shared/architecture_city/README.md` | 明确用于场景/建筑提示，不替代世界观规则 | P2 |

