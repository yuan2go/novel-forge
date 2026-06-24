# Tasks

## 1. 模块目标

`tasks/` 是 `novel-forge` 的项目级任务系统骨架，用于记录可交给 Claude Code、Codex、DeepSeek、ChatGPT 和质量检查 Agent 执行的任务。

## 2. 输入

- 项目路线图
- AI workflow 文档
- 任务需求
- 相关源码、文档、模板或小说 workspace 文件

## 3. 输出

- 标准任务卡
- backlog
- 执行状态
- 验收记录

## 4. 文件路径

```text
tasks/
├── README.md
├── backlog.md
└── task-template.md
```

## 5. 执行流程

1. 在 `backlog.md` 记录任务候选。
2. 对可执行任务复制 `task-template.md`。
3. 填写目标、输入、输出、允许修改范围、禁止事项和验收标准。
4. 指派 Agent。
5. 执行完成后补充变更摘要、检查结果和状态。

## 6. 验收标准

- 每个执行任务都有任务卡。
- 每个任务卡都有明确输入、输出和边界。
- 每个任务有状态。
- 工程任务附带检查结果。
- 写作任务附带审稿或质量检查入口。

## 7. 风险与边界

- `tasks/` 只管理项目级任务，不替代单本小说 workspace 内的 `08_tasks/task_cards/`。
- 不允许通过任务卡绕过项目宪法。
- 不允许通过任务卡授权写入真实密钥或私有素材。
