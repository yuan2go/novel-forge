# PROJECT_STATE

## 1. 模块目标

记录 `novel-forge` 仓库的当前阶段、已完成内容、待完成内容、风险和下一步任务，避免项目状态只存在于对话上下文中。

## 2. 输入

- `README.md`
- `ROADMAP.md`
- `CLAUDE.md`
- `AGENTS.md`
- `docs/novel-forge-v4-final.md`
- `docs/audits/v4-business-audit.md`
- `docs/audits/v4-module-matrix.md`
- `docs/audits/v4-risk-register.md`
- `docs/audits/v4-next-actions.md`

## 3. 输出

- 当前项目阶段
- 当前实现状态
- 当前风险
- 下一步优先任务
- 最近质量检查结果

## 4. 文件路径

```text
PROJECT_STATE.md
```

## 5. 执行流程

1. 每次完成架构、流程、脚本、模板或测试层面的关键任务后更新本文件。
2. 将当前阶段、已完成项、未完成项和风险写入文件。
3. 如果进入下一阶段，先更新 `CURRENT_GOAL.md` 和 `DECISIONS.md`。
4. 不在本文件中保存真实密钥、版权文本或私有素材。

## 6. 当前阶段

当前阶段：V4 最小可运行闭环准备阶段。

实际实现状态：V1 文件项目制骨架已存在，V4 业务蓝图已完成文档化，正在补齐 V4 最小工程治理能力。

当前判断：

- 文档目标已经覆盖 V4 小说工业化生产系统。
- 工程实现仍以 V1 骨架为主。
- 当前优先级不是扩大功能，而是冻结目录、补状态文件、补 schema、补基础校验。

## 7. 已完成内容

- `README.md` 定义项目目标和 V1 核心链路。
- `AGENTS.md` 定义 AI Agent 协作规则。
- `CLAUDE.md` 定义 Claude Code 项目级总控规则。
- `docs/` 已包含 V1 架构文档、AI workflow 文档和 V4 总蓝图。
- `docs/audits/` 已生成 V4 审计报告、模块矩阵、风险登记表和下一步任务表。
- `templates/` 已包含 Gate、项目宪法、任务卡、细纲、审稿和项目注册表模板。
- `scripts/check_docs_structure.py` 可检查 V1 文档、模板和脚本存在性。
- `scripts/check_docs_structure.py` 已扩展为 V4 治理结构检查，覆盖状态文件、progress、audits、architecture、AI workflow、tasks 和第一批 schema。
- `scripts/init_novel_project.py` 已支持 `--dry-run`，可在不写入、不删除的情况下输出初始化计划。
- `scripts/init_novel_project.py` 可初始化 V1 单本小说 workspace 骨架。
- `tests/test_structure.py` 可运行基础结构测试。
- `schemas/` 开始落地第一批 V4 核心 schema。

## 8. 待完成内容

- `init_novel_project.py` 仍需要补齐更完整的 workspace 文件。
- 素材导入、清洗、拆解、题材生成、审稿和反馈流程尚未形成可运行 pipeline。
- 核心 schema 还需要继续扩展到 world、character、outline、feedback、discipline_card。
- 质量门禁 QG-0 到 QG-5 仍需落成模板和检查脚本。
- 模型路由配置和调用日志尚未落地。

## 9. 当前风险

- V4 文档目标明显超前于当前工程实现。
- V1 编号目录与 V4 语义目录并存，若不冻结映射关系，后续数据会分散。
- 缺少数据来源、版权边界、抽象等级和 forbidden usage 的强制校验。
- 正文生成、审稿和反馈反哺尚未形成闭环。
- 当前测试覆盖较浅，只能保证基础文件存在，不能保证业务链路正确。

## 10. 下一步任务

P0：

- 补齐 workspace 初始化文件，使其满足 Claude Code 接管最低条件。
- 新增质量门禁模板。

P1：

- 新增热门小说拆解模板和专业知识卡模板。
- 新增题材、世界观、人物、反馈 schema。
- 建立模型路由配置草案。

## 11. 最近质量检查

最近检查命令：

```bash
make check
make test
```

最近结果：Loop 2 完成 `V4-P0-005` 后，`make check` 通过，`make test` 通过，当前测试数为 16。

## 12. 验收标准

- 本文件能回答项目当前处于什么阶段。
- 本文件能列出已完成内容、待完成内容和当前风险。
- Claude Code 进入仓库后可通过本文件恢复项目状态。
- 本文件不包含真实密钥、私有素材或版权文本。

## 13. 风险与边界

- 本文件是项目状态摘要，不替代 `ROADMAP.md`。
- 本文件不授权任何 Agent 修改终稿、项目宪法或世界宪法。
- 本文件不保存模型输出正文或原始素材。
