# Codex Task Template

## 1. 模块目标

为 Codex 工程副编提供标准任务卡格式，确保每次工程改动都有清晰目标、输入、输出、权限边界和验收标准。

## 2. 输入

- `AGENTS.md`
- `CLAUDE.md`
- `README.md`
- `ROADMAP.md`
- 相关 `docs/`
- 相关 `templates/`
- 相关 `scripts/`
- 相关 `tests/`
- 本任务卡

## 3. 输出

- 变更文件列表
- diff 摘要
- 测试结果
- 风险与未完成事项
- 如适用：新增或修改后的脚本、测试、模板、文档

## 4. 文件路径

建议路径：

```text
tasks/task_YYYYMMDD_short_name.md
```

## 5. 执行流程

1. 读取任务卡和相关规则文件。
2. 只读扫描目标文件。
3. 明确变更范围和不变更范围。
4. 执行最小必要修改。
5. 运行必要检查。
6. 输出变更文件列表、diff 摘要和测试结果。

## 6. 验收标准

- 未修改任务卡禁止范围内的文件。
- 未安装依赖。
- 未删除已有文件。
- 保持 Python 3.11+ 标准库约束。
- `make check` 通过，或说明无法运行的原因。
- 涉及脚本、模板或测试时，`make test` 通过，或说明无法运行的原因。

## 7. 风险与边界

- 不得改变 V1 总路线。
- 不得引入数据库、外部服务或复杂 Agent 平台。
- 不得修改单本小说终稿、项目宪法或世界宪法，除非任务卡明确授权。
- 不得读取或写入真实密钥。

## Task

### task_id

`task_YYYYMMDD_short_name`

### task_type

`engineering | docs | template | test | review | scaffold`

### objective

说明本次任务要达成的具体结果。

### context

说明为什么需要本任务，以及依赖哪些已有文件。

### input_files

- `AGENTS.md`
- `CLAUDE.md`

### allowed_changes

- `docs/`
- `templates/`
- `scripts/`
- `tests/`
- `tasks/`

### forbidden_changes

- `*_final.md`
- `project_constitution.md`
- `world_constitution.md`
- 真实密钥或私有素材

### expected_outputs

- 变更文件列表
- diff 摘要
- 检查结果

### acceptance

- 任务目标完成。
- 验收标准全部满足。
- 未完成风险已列出。
