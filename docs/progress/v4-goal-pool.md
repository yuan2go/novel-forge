# V4 Goal Pool

## 1. 模块目标

记录 `novel-forge` V4 目标循环模式下的开发目标池，作为后续每轮选择单一目标的事实来源。

## 2. 输入

- `CLAUDE.md`
- `README.md`
- `ROADMAP.md`
- `PROJECT_STATE.md`
- `CURRENT_GOAL.md`
- `DECISIONS.md`
- `docs/novel-forge-v4-final.md`
- `docs/architecture/v4-minimum-structure.md`
- `docs/audits/v4-business-audit.md`
- `docs/audits/v4-module-matrix.md`
- `docs/audits/v4-risk-register.md`
- `docs/audits/v4-next-actions.md`
- `scripts/`
- `schemas/`
- `tests/`
- `templates/`

## 3. 输出

V4 目标池表格，包含目标编号、模块、目标描述、当前状态、涉及文档、涉及代码、验收标准和优先级。

## 4. 文件路径

```text
docs/progress/v4-goal-pool.md
```

## 5. 执行流程

1. Loop 0 建立目标池。
2. 每轮 Loop N 只能选择一个目标推进。
3. 每轮完成后更新目标状态。
4. P0 全部完成后生成 `docs/progress/v4-final-acceptance.md`。

## 6. 验收标准

- 覆盖 V4 主链路 P0。
- 明确区分已完成、部分完成、仅有设计、未开始、阻塞。
- 每个目标有可检查验收标准。

## 7. 风险与边界

- 本文件不是任务执行授权，执行前仍需在轮次报告中选择单个目标。
- 不得把“仅有文档设计”标为“已完成”。
- 不得一次性执行多个不相关目标。

## Goal Pool

| 目标编号 | 模块 | 目标描述 | 当前状态 | 涉及文档 | 涉及代码 | 验收标准 | 优先级 |
|---|---|---|---|---|---|---|---|
| V4-P0-001 | 状态管理 | 建立 `PROJECT_STATE.md`、`CURRENT_GOAL.md`、`DECISIONS.md` | 已完成 | `docs/novel-forge-v4-final.md`、`docs/audits/v4-next-actions.md` | 根目录 Markdown | 三个状态文件存在；内容可追踪；不含敏感内容 | P0 |
| V4-P0-002 | 目录架构 | 输出 V4 最小目录冻结文档，明确 V1/V4 兼容关系 | 已完成 | `docs/architecture/v4-minimum-structure.md` | 无 | 文档说明保留目录、按 pipeline 落地目录、暂缓能力和数据边界 | P0 |
| V4-P0-003 | Schema | 新增第一批核心 schema：material、dissection、topic、chapter_plan、review | 已完成 | `docs/novel-forge-v4-final.md` 第 4、12、14、18、20 节 | `schemas/*.schema.json`、`tests/test_schemas.py` | 五个 schema 是合法 JSON；测试验证基础结构 | P0 |
| V4-P0-004 | 结构校验 | 扩展 `make check`，覆盖 V4 进度文件、状态文件、schema 和新增 docs 目录 | 已完成 | `CLAUDE.md`、`docs/ai-workflow/acceptance-criteria.md`、`docs/architecture/v4-minimum-structure.md` | `scripts/check_docs_structure.py`、`tests/test_structure.py`、`tests/test_check_docs_structure.py` | 缺关键 V4 治理文件时 `make check` 失败；正常状态通过；错误提示清晰 | P0 |
| V4-P0-005 | Workspace 安全 | 为 `init_novel_project.py` 增加 `--dry-run`，避免误写入和 `--force` 删除风险 | 已完成 | `CLAUDE.md`、`docs/09_novel_workspace.md`、`docs/audits/v4-risk-register.md` | `scripts/init_novel_project.py`、`tests/test_init_novel_project.py` | `--dry-run` 输出计划但不创建目录；原初始化仍可用；`make test` 通过 | P0 |
| V4-P0-006 | Workspace 接管条件 | 补齐初始化 workspace 最低接管文件，贴近 `docs/09_novel_workspace.md` 和 `docs/10_claude_code_execution.md` | 未开始 | `docs/09_novel_workspace.md`、`docs/10_claude_code_execution.md`、`docs/07_knowledge_compiler.md` | `scripts/init_novel_project.py`、`templates/`、测试 | 初始化结果包含 world、characters、serialization_plan、current_sprint、style 文件和基础 knowledge pack 文件 | P0 |
| V4-P0-007 | 素材导入 | 建立最小素材导入入口，只处理元数据和允许的文本路径，不导入真实版权内容 | 未开始 | `docs/novel-forge-v4-final.md` 第 4、12、22、23 节 | `scripts/ingest/`、`schemas/material.schema.json`、测试 | 可用 CLI 写入/校验 material metadata；错误输入失败；不保存真实密钥或版权原文 | P0 |
| V4-P0-008 | 文本清洗 | 建立最小文本清洗入口，区分 raw、cleaned、metadata | 未开始 | V4 第 12、13、23 节；`docs/architecture/v4-minimum-structure.md` | `scripts/clean/`、测试 | 可清洗样例文本到输出路径；保留来源 metadata；空输入/缺路径有明确错误 | P0 |
| V4-P0-009 | 热门小说拆解 | 建立拆解报告模板与最小生成/校验入口，只输出抽象结构与禁用项 | 未开始 | V4 第 3、12、24、26 节；`docs/16_risk_control.md` | `templates/novel_dissection_template.md`、`scripts/extract/`、`schemas/dissection.schema.json`、测试 | 能生成或校验 dissection JSON/Markdown；包含 reusable/forbidden/copy_risk；不保存可仿写表达 | P0 |
| V4-P0-010 | 题材生成 | 建立题材卡模板和最小校验入口，使拆解资产可转化为候选题材 | 未开始 | V4 第 14、23、24 节；`docs/04_project_incubation.md` | `templates/topic_card_template.md`、`scripts/validate/`、`schemas/topic.schema.json`、测试 | 题材卡有卖点、读者期待、差异化、冲突和风险；校验失败提示清楚 | P0 |
| V4-P0-011 | 质量门禁 | 建立 QG-0 到 QG-5 质量门禁模板和基础校验 | 未开始 | V4 第 24 节；`docs/12_review_system.md`、`docs/16_risk_control.md` | `templates/quality_gate.md`、可选 `scripts/validate/`、测试 | 每个门禁有输入、检查项、通过/退回标准；至少能校验细纲/审稿门禁文件存在 | P0 |
| V4-P0-012 | 审稿入口 | 建立 review schema 对应的审稿报告样例/校验入口 | 未开始 | V4 第 20、24、26 节；`docs/12_review_system.md` | `schemas/review.schema.json`、`templates/review_report.md`、测试 | 审稿对象、评分、问题、修改建议、final_decision 可校验；不把未审稿正文标记为 final | P0 |
| V4-P0-013 | 测试日志与循环状态 | 每轮目标完成后维护 progress 文件和测试日志 | 部分完成 | 本文件、`docs/progress/v4-test-log.md`、`docs/progress/v4-loop-report.md` | 无 | 每轮有目标选择、测试记录、验收判断和下一步建议 | P0 |
| V4-P1-001 | 多学科知识解析 | 新增 discipline_card schema、模板和校验 | 未开始 | V4 第 9、13 节；`docs/02_global_assets.md` | `schemas/discipline_card.schema.json`、`templates/discipline_card_template.md` | 知识卡包含 source、core_concept、story_function、genre_usage、avoid | P1 |
| V4-P1-002 | 世界观生成 | 新增 world schema、模板和项目/全局边界说明 | 未开始 | V4 第 15 节；`docs/03_world_lab.md` | `schemas/world.schema.json`、`templates/worldview_template.md` | 世界观包含 core_rule、power/resource/political/geography/history/conflict_engine | P1 |
| V4-P1-003 | 人物生成 | 新增 character schema、模板和动机链检查 | 未开始 | V4 第 16 节；`docs/07_knowledge_compiler.md` | `schemas/character.schema.json`、`templates/character_card_template.md` | 人物卡包含欲望、恐惧、创伤、资源处境、关系网和成长线 | P1 |
| V4-P1-004 | 大纲生成 | 新增 outline schema、模板和卷纲结构 | 未开始 | V4 第 17 节；`docs/11_writing_pipeline.md` | `schemas/outline.schema.json`、`templates/outline_template.md` | 总纲/卷纲包含主线、卷目标、高潮、长线钩子和风险 | P1 |
| V4-P1-005 | 反馈导入 | 新增 feedback schema、模板和最小评论分类入口 | 未开始 | V4 第 21 节；`docs/13_feedback_control.md` | `schemas/feedback.schema.json`、`templates/feedback_report_template.md`、脚本 | 反馈可记录来源、分类、频次、采纳建议、影响章节和宪法检查 | P1 |
| V4-P1-006 | 模型路由 | 建立 `.novelforge/model_routing.yaml` 草案与无密钥校验 | 未开始 | `docs/15_model_routing.md`、V4 第 8 节 | `.novelforge/model_routing.yaml`、测试 | 配置覆盖拆解、题材、正文、审稿、反馈；不包含 API Key | P1 |
| V4-P1-007 | 正文版本流转 | 建立正文草稿/修订/final/published 版本规范和样例路径 | 未开始 | V4 第 19 节；`docs/11_writing_pipeline.md` | `templates/chapter_draft_template.md`、可选 docs | 明确 draft/revised/final/published 边界和 final 保护 | P1 |
| V4-P2-001 | 训练题系统 | 建立 training 目录骨架和作文/阅读训练模板 | 未开始 | V4 第 27 节 | `training/README.md`、模板 | 训练题与正式正文分离；有输入输出和验收标准 | P2 |
| V4-P2-002 | 建筑/图像提示词 | 建立建筑/城市提示词库骨架 | 未开始 | V4 第 9、31 节 | `prompts/shared/architecture_city/README.md` | 明确用于场景/建筑提示，不替代世界观规则 | P2 |
| V4-P2-003 | 检索预研 | 输出文件制知识库到未来向量库的接口建议 | 未开始 | V4 第 22 节 | 文档 | 不引入数据库，仅明确未来索引字段和边界 | P2 |
