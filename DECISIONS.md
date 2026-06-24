# DECISIONS

## 1. 模块目标

记录 `novel-forge` 的关键架构和流程决策，确保后续 Agent 能理解为什么当前项目这样组织。

## 2. 输入

- 用户任务指令
- `docs/novel-forge-v4-final.md`
- `docs/audits/v4-business-audit.md`
- `docs/audits/v4-risk-register.md`
- 实际仓库结构

## 3. 输出

- 决策编号
- 决策内容
- 决策原因
- 影响范围
- 后续动作

## 4. 文件路径

```text
DECISIONS.md
```

## 5. 执行流程

1. 发生目录、数据结构、模型协作、质量门禁或路线变更时新增决策记录。
2. 每条决策必须包含原因和影响范围。
3. 废弃或替代决策时新增记录，不直接删除旧决策。
4. 不记录真实密钥、私有素材或版权文本。

## 6. 决策记录

### DEC-0001：V4 暂不执行大规模目录迁移

日期：2026-06-24

决策：

当前保留 V1 文件项目制目录与脚本，不立即把仓库重构为完整 V4 目录树。

原因：

- `ROADMAP.md` 仍声明当前优先推进 V1。
- `docs/novel-forge-v4-final.md` 是 V4 目标蓝图，实际工程能力尚未支撑完整 V4。
- 直接创建全部 V4 目录会造成空目录膨胀和维护成本上升。

影响范围：

- `04_novel_projects/` 继续作为单本小说 workspace 默认输出目录。
- `data/`、`knowledge/`、`factory/`、`manuscripts/` 等 V4 目录只在对应 pipeline 落地时创建。
- 先用 `docs/architecture/v4-minimum-structure.md` 冻结兼容策略。

后续动作：

- 先补状态文件、schema 和测试。
- 再实现素材导入、清洗、拆解、题材生成的最小闭环。

### DEC-0002：第一批 schema 先覆盖主链路核心对象

日期：2026-06-24

决策：

第一批 schema 只新增 `material`、`dissection`、`topic`、`chapter_plan`、`review`。

原因：

- 这五类对象覆盖从素材、拆解、题材、细纲到审稿的最小链路。
- 当前不宜一次性定义所有 V4 schema，避免未验证前过度建模。
- 使用 Python 标准库测试 schema JSON 结构，不引入 `jsonschema` 依赖。

影响范围：

- `schemas/` 先只保存核心 JSON schema。
- `tests/test_schemas.py` 只验证 schema 文件可解析和基础字段一致性。

后续动作：

- P1 再补 `discipline_card`、`world`、`character`、`outline`、`feedback`。

### DEC-0003：文档仍是当前唯一长期记忆

日期：2026-06-24

决策：

在引入数据库、索引或向量库之前，Markdown、JSON、YAML 和 Git 仍是唯一长期记忆。

原因：

- 当前仓库尚未实现数据库或检索层。
- 文件制更符合当前 V1 到 V4 最小闭环过渡阶段。
- 便于 Claude Code、Codex 和其他 Agent 直接读取和审计。

影响范围：

- 关键状态写入 `PROJECT_STATE.md`、`CURRENT_GOAL.md`、`DECISIONS.md`。
- 后续任务不能只在聊天中保存项目状态。

后续动作：

- 将状态文件纳入后续结构检查。

## 7. 验收标准

- 每条决策都有编号、日期、内容、原因、影响范围和后续动作。
- 后续 Agent 能根据本文件理解目录、schema 和状态管理策略。
- 决策记录不删除历史，只追加。

## 8. 风险与边界

- 本文件记录决策，不替代任务卡。
- 本文件不授权破坏 V1 路线或绕过重大变更审查。
- 本文件不保存具体小说正文或素材。
