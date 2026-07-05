# Novel OS Skills Installation Check

日期：2026-07-05

## 1. 本次结论

本次任务没有安装外部 Skill，没有运行 `npx skills add`，没有修改 `.claude/skills` runtime copy。

已使用 runtime 内置 Skill：

- `skill-creator`

原因：当前任务是完善项目 Skill 选择、安装、治理和记录策略，`skill-creator` 适合更新 Skill 规范与治理文档；项目本地 Skill 和已有 runtime Skill 已能覆盖任务，不需要外部安装。

## 2. 安装/使用记录

| Skill | 来源 | 本地路径 | 使用阶段 | 使用原因 | 风险 | 是否安装 | 是否同步 | 是否更新映射 |
| ----- | -- | ---- | ---- | ---- | -- | ---- | ---- | ------ |
| `skill-creator` | Claude Code system skill | `/Users/yuan/.codex-claude/skills/.system/skill-creator/SKILL.md` | Skill governance policy update | 指导 Skill 更新、触发边界、验证和运行时副本策略 | 低；只读系统 Skill，无脚本执行 | 否，已存在 | 否 | 否 |

## 3. 外部 Skill 安装检查

| 检查项 | 结果 |
| -- | -- |
| 是否访问 `skills.sh` 安装 Skill | 否 |
| 是否从 Anthropic GitHub Skill 仓库安装 Skill | 否 |
| 是否运行 `npx skills add` | 否 |
| 是否修改 `.claude/skills` | 否 |
| 是否需要许可证新增审查 | 否 |
| 是否执行未知脚本 | 否 |
| 是否需要 API key / token | 否 |

## 4. 后续安装要求

后续如需安装外部 Skill，必须先按 `docs/09-skills/usage-policy.md` 完成安装前检查，并在本文件记录：

- Skill 名称；
- 来源 URL；
- commit 或版本；
- 许可证；
- 安装命令；
- 安装路径；
- 脚本/依赖/网络行为；
- 验证命令；
- 是否同步到 `.claude/skills`；
- 是否更新 Agent-Skill Map。
