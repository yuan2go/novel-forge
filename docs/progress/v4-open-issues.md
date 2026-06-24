# V4 Open Issues

## 1. 模块目标

记录 V4 目标循环中尚未解决的问题、阻塞点和需要主编决策的事项。

## 2. 输入

- `docs/progress/v4-goal-pool.md`
- `docs/audits/v4-risk-register.md`
- 每轮测试和验收结果

## 3. 输出

开放问题列表。

## 4. 文件路径

```text
docs/progress/v4-open-issues.md
```

## 5. 执行流程

1. 发现阻塞或风险时追加记录。
2. 问题解决后更新状态，不删除历史。
3. 需要用户决策的问题标记为 `needs_decision`。

## 6. 验收标准

- 每个问题有编号、类型、描述、影响、状态和建议处理方式。
- 不隐藏未解决风险。

## 7. 风险与边界

- 本文件不是缺陷修复计划，只记录开放问题。
- 修复仍需通过目标池选择单目标执行。

| 问题编号 | 类型 | 描述 | 影响 | 状态 | 建议处理 |
|---|---|---|---|---|---|
| OI-001 | 结构校验 | `make check` 当前仍只覆盖 V1 文件，未覆盖 `CLAUDE.md`、状态文件、`docs/progress/`、`docs/audits/`、`docs/architecture/`、`schemas/` | 新增 V4 治理文件可能缺失但检查仍通过 | resolved | 已通过 `V4-P0-004` 修复 |
| OI-002 | Workspace 安全 | `init_novel_project.py` 无 `--dry-run`，`--force` 会删除已有项目目录 | 可能误删单本小说 workspace | resolved | 已通过 `V4-P0-005` 增加 `--dry-run` 并补测试 |
| OI-003 | Workspace 完整性 | 初始化 workspace 缺少 docs 要求的多个接管文件，如 `world_constitution.md`、`characters.md`、`serialization_plan.md`、`current_sprint.md` | Claude Code 接管条件不足 | open | 执行 `V4-P0-006` |
| OI-004 | 主链路入口 | 素材导入、清洗、拆解、题材生成尚无 CLI 入口 | V4 主链路无法运行 | open | 依次执行 `V4-P0-007` 到 `V4-P0-010` |
| OI-005 | 质量门禁 | QG-0 到 QG-5 只有 V4 文档设计，没有模板和校验 | 无法阻止低质量或高风险产物进入下游 | open | 执行 `V4-P0-011` |
| OI-006 | 工作区脏状态 | 当前仓库存在多个未跟踪文件和一个 `.claude/commands/v4-loop.md` | 提交前需要人工确认归属 | open | 不删除；后续提交前由用户决定 |
