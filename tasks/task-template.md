# Task Template

## 1. 模块目标

定义 `novel-forge` 项目级任务卡的统一格式。

## 2. 输入

- `AGENTS.md`
- `CLAUDE.md`
- 相关项目文件
- 任务上下文

## 3. 输出

- 明确的执行结果
- 变更文件列表
- diff 摘要
- 检查结果
- 风险与未完成事项

## 4. 文件路径

```text
tasks/task_YYYYMMDD_short_name.md
```

## 5. 执行流程

1. 填写任务元信息。
2. 明确允许修改和禁止修改的文件。
3. 指派合适 Agent。
4. 执行前读取规则文件和输入文件。
5. 执行后记录结果、检查命令和风险。

## 6. 验收标准

- 任务目标清晰。
- 输入和输出明确。
- 权限边界明确。
- 验收标准可检查。
- 结果记录完整。

## 7. 风险与边界

- 任务卡不得授权读取真实密钥。
- 任务卡不得授权无审稿覆盖终稿。
- 任务卡不得绕过重大变更审查规则。

## Task Card

### task_id

`task_YYYYMMDD_short_name`

### title

待填写。

### status

`proposed | ready | in_progress | review | accepted | blocked`

### assigned_agent

`Claude Code | Codex | DeepSeek | ChatGPT | Knowledge Agent | Asset Agent | Quality Agent`

### objective

待填写。

### input_files

- 待填写。

### output_files

- 待填写。

### allowed_changes

- 待填写。

### forbidden_changes

- `*_final.md`
- `project_constitution.md`
- `world_constitution.md`
- 真实密钥或私有素材

### execution_steps

1. 待填写。

### acceptance_criteria

- 待填写。

### validation_commands

```bash
make check
make test
```

### result_summary

待执行后填写。

### risks

待填写。
