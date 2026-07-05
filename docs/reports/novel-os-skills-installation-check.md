# Novel OS Skills Installation Check

日期：2026-07-05

## 1. 本次结论

本次任务没有安装外部 Skill，没有运行 `npx skills add`。本次新增 5 个项目 root Skill，其中上一轮新增 `provider-runtime-policy`、`canon-continuity-graph`、`publish-release-gate-os`，本轮新增 `narrative-beat-design`、`skill-governance`，并通过 `make sync-skills` 将 root `skills/` 同步到 `.claude/skills` runtime copy。

已使用 runtime 内置 Skill：

- `skill-creator`

原因：当前任务是完善项目 Skill 选择、安装、治理和记录策略，`skill-creator` 适合更新 Skill 规范与治理文档；项目本地 Skill 和已有 runtime Skill 已能覆盖任务，不需要外部安装。

已只读参考但未安装、未 vendor 的外部个人 Skill：

- `writing-beats`
- `writing-great-skills`
- `writing-plans`
- `writing-fragments`
- `writing-shape`

处理结果：

- `writing-beats` 的 grounding / beat path 方法已改写进入 `narrative-beat-design`、`chapter-outline`、`long-outline`。
- `writing-great-skills` 的 predictable / single source of truth / progressive disclosure 方法已改写进入 `skill-governance` 和 `usage-policy`。
- `writing-plans` 的工程计划格式已改写进入 `project-planning`。
- `writing-fragments`、`writing-shape` 保持外部个人写作 Skill，不进入项目源 Skill。

新增项目 Skill：

- `provider-runtime-policy`
- `canon-continuity-graph`
- `publish-release-gate-os`
- `narrative-beat-design`
- `skill-governance`

## 2. 安装/使用记录

| Skill | 来源 | 本地路径 | 使用阶段 | 使用原因 | 风险 | 是否安装 | 是否同步 | 是否更新映射 |
| ----- | -- | ---- | ---- | ---- | -- | ---- | ---- | ------ |
| `skill-creator` | Claude Code system skill | `/Users/yuan/.codex-claude/skills/.system/skill-creator/SKILL.md` | Skill governance policy update | 指导 Skill 更新、触发边界、验证和运行时副本策略 | 低；只读系统 Skill，无脚本执行 | 否，已存在 | 否 | 否 |
| `provider-runtime-policy` | project root skill | `skills/provider-runtime-policy/SKILL.md` | Novel OS acceptance completion | 补齐 provider hard-stop、fallback、cost/token、model_call_log、cost_ledger 边界 | 中；无脚本，无外部依赖 | 新增项目 Skill，非外部安装 | 是 | 是 |
| `canon-continuity-graph` | project root skill | `skills/canon-continuity-graph/SKILL.md` | Novel OS acceptance completion | 补齐 Canon Graph、continuity conflict、invalidation、rollback 约束 | 中；无脚本，无外部依赖 | 新增项目 Skill，非外部安装 | 是 | 是 |
| `publish-release-gate-os` | project root skill | `skills/publish-release-gate-os/SKILL.md` | Novel OS acceptance completion | 补齐 ReleasePackage、PublishGateReport、rollback/resume 发布闭环 | 中；无脚本，无外部依赖 | 新增项目 Skill，非外部安装 | 是 | 是 |
| `narrative-beat-design` | project root skill | `skills/narrative-beat-design/SKILL.md` | Narrative planning method absorption | 补齐 reader grounding、beat path、hook/payoff path，用于 `long-outline` / `chapter-outline` | 中；无脚本，无外部依赖 | 新增项目 Skill，非外部安装 | 是 | 是 |
| `skill-governance` | project root skill | `skills/skill-governance/SKILL.md` | Skill governance method absorption | 补齐 predictable trigger、single source of truth、progressive disclosure、vendor/license/sync 边界 | 中；无脚本，无外部依赖 | 新增项目 Skill，非外部安装 | 是 | 是 |
| `writing-beats` / `writing-great-skills` / `writing-plans` | external personal skill | `/Users/yuan/.agents/skills/.../SKILL.md` | External method review | 只读参考方法并改写到项目源 Skill，不复制目录或原文 | 中；外部个人 Skill，不作为项目 source of truth | 否 | 否，未 vendor | 是，方法已吸收 |
| `writing-fragments` / `writing-shape` | external personal skill | `/Users/yuan/.agents/skills/.../SKILL.md` | External method review | 判定为个人写作探索/成文流程，暂不进入项目源 Skill | 中；与项目生产资产边界不直接匹配 | 否 | 否，保留外部 | 否 |

## 3. 外部 Skill 安装检查

| 检查项 | 结果 |
| -- | -- |
| 是否访问 `skills.sh` 安装 Skill | 否 |
| 是否从 Anthropic GitHub Skill 仓库安装 Skill | 否 |
| 是否运行 `npx skills add` | 否 |
| 是否直接 vendor 外部 writing Skill 到 root `skills/` | 否 |
| 是否修改 `.claude/skills` | 是，通过 `make sync-skills` 从 root `skills/` 生成 runtime copy |
| 是否需要许可证新增审查 | 否，新增内容为项目 root Skill 的改写方法；外部 writing Skill 未复制、未 vendor |
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
