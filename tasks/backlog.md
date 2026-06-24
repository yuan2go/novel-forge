# Backlog

## 1. 模块目标

记录 `novel-forge` 项目级待办任务，作为任务卡创建前的轻量队列。

## 2. 输入

- `ROADMAP.md`
- 项目审查结论
- AI workflow 需求
- 测试和验收缺口

## 3. 输出

- 待办任务列表
- 优先级
- 建议执行 Agent
- 状态

## 4. 文件路径

```text
tasks/backlog.md
```

## 5. 执行流程

1. 新需求先进入 Backlog。
2. 明确优先级、建议 Agent 和验收口径。
3. 进入执行前复制 `tasks/task-template.md` 创建独立任务卡。
4. 任务完成后更新状态和结果链接。

## 6. 验收标准

- 每条任务都有优先级。
- 每条任务都有建议 Agent。
- 每条任务都有状态。
- 可执行任务能追溯到独立任务卡。

## 7. 风险与边界

- Backlog 不是授权文件，不能替代任务卡。
- P0/P1 任务仍需明确修改范围。
- 涉及重大架构变化的任务必须先输出审查报告。

## Items

| ID | Priority | Task | Suggested Agent | Status |
| --- | --- | --- | --- | --- |
| NF-001 | P1 | 为 `init_novel_project.py` 增加真正的 `--dry-run`，并补测试 | Codex | proposed |
| NF-002 | P1 | 扩展结构校验，覆盖 `tasks/` 和 `docs/ai-workflow/` | Codex | proposed |
| NF-003 | P1 | 建立模板字段完整性测试 | Codex | proposed |
| NF-004 | P2 | 同步 `ROADMAP.md` 中 V1.2 已完成项 | Codex | proposed |
| NF-005 | P2 | 创建示例项目输入文件但不生成 workspace | Codex | proposed |
