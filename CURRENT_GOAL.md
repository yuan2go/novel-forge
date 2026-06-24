# CURRENT_GOAL

## 1. 模块目标

记录 `novel-forge` 当前唯一优先目标，避免多条路线并行导致执行失焦。

## 2. 输入

- `PROJECT_STATE.md`
- `docs/audits/v4-next-actions.md`
- `docs/audits/v4-risk-register.md`
- 用户当前任务指令

## 3. 输出

- 当前目标
- 输入文件
- 输出文件
- 允许修改范围
- 验收标准
- 完成后动作

## 4. 文件路径

```text
CURRENT_GOAL.md
```

## 5. 执行流程

1. 每次开始新的 P0/P1/P2 任务前更新当前目标。
2. 明确本轮允许修改的文件范围。
3. 任务完成后记录检查命令和下一步动作。
4. 不把聊天记录当成长期状态。

## 6. 当前唯一目标

目标：继续完成 V4 P0 主链路基础能力。

本轮具体目标：

1. 已完成 `V4-P0-005`：为 `init_novel_project.py` 增加 `--dry-run`。
2. 下一轮建议执行 `V4-P0-006`：补齐初始化 workspace 最低接管文件。

## 7. 输入文件

- `CLAUDE.md`
- `AGENTS.md`
- `docs/novel-forge-v4-final.md`
- `docs/progress/v4-goal-pool.md`
- `docs/progress/v4-open-issues.md`
- `scripts/init_novel_project.py`
- `tests/test_init_novel_project.py`

## 8. 输出文件

- `scripts/init_novel_project.py`
- `tests/test_init_novel_project.py`
- `docs/progress/v4-goal-pool.md`
- `docs/progress/v4-test-log.md`
- `docs/progress/v4-loop-report.md`
- `docs/progress/v4-open-issues.md`

## 9. 允许修改范围

- `scripts/`
- `tests/`
- `docs/progress/`
- 根目录状态文件

## 10. 禁止事项

- 不修改业务正文。
- 不删除已有文件。
- 不安装依赖。
- 不引入数据库或外部服务。
- 不把真实版权文本放入 `data/` 或 schema 示例。

## 11. 验收标准

- `--dry-run` 输出计划但不创建目录。
- `--dry-run --force` 不删除已有项目目录。
- 普通初始化仍可创建项目文件。
- `make check` 通过。
- `make test` 通过。

## 12. 完成后动作

完成后建议下一步处理 workspace 标准结构对齐。

## 13. 风险与边界

- 当前目标只建立治理基础，不实现完整素材 pipeline。
- schema 只做第一批核心对象，不代表 V4 数据模型最终冻结。
- 目录冻结文档是兼容策略，不立即执行大规模迁移。
