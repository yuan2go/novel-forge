# Novel OS Skills Governance Audit

日期：2026-07-05

## 1. 审计目标

建立 Novel Forge / Novel OS 的 Skill 自主选择、安装、同步和治理记录规则，避免固定列表式使用、无差别安装、许可证污染、外部脚本风险和 `.claude/skills` 手工漂移。

## 2. 当前治理状态

| 项目 | 当前状态 | 证据 |
| -- | -- | -- |
| 根目录 `skills/` 是 source of truth | 已明确 | `docs/09-skills/README.md`、`docs/09-skills/runtime-sync.md` |
| `.claude/skills` 是 runtime copy | 已明确 | `docs/09-skills/runtime-sync.md` |
| 不直接手工编辑 runtime copy | 已明确 | `docs/09-skills/runtime-sync.md`、`docs/09-skills/usage-policy.md` |
| Skill 自主发现顺序 | 已补齐 | `docs/09-skills/usage-policy.md` |
| 外部 Skill 安装前检查 | 已补齐 | `docs/09-skills/usage-policy.md` |
| 外部 Skill 安装后验证 | 已补齐 | `docs/09-skills/usage-policy.md` |
| Skill 使用/安装记录表 | 已补齐 | `docs/09-skills/usage-policy.md`、本报告 |
| Agent-Skill Map | 已补齐 Novel OS 专用 Skill | `docs/09-skills/agent-skill-map.md`、`AGENTS.md` |
| 许可证边界 | 已补齐 | `docs/09-skills/usage-policy.md` |

## 3. 使用/安装记录

| Skill | 来源 | 本地路径 | 使用阶段 | 使用原因 | 风险 | 是否安装 | 是否同步 | 是否更新映射 |
| ----- | -- | ---- | ---- | ---- | -- | ---- | ---- | ------ |
| `skill-creator` | Claude Code system skill | `/Users/yuan/.codex-claude/skills/.system/skill-creator/SKILL.md` | Skill governance policy update | 按 Skill 最佳实践完善选择、安装、验证和记录策略 | 低；只读使用，无安装，无脚本执行 | 否，已存在 | 否 | 否 |

## 4. 当前推荐执行规则

每个阶段开始前输出：

```text
Skill selection:
- Task:
- Candidate skills:
- Selected skills:
- Reason:
- Install needed:
- Risk:
```

选择顺序：

1. `skills/`
2. `.claude/skills/`
3. `docs/09-skills/agent-skill-map.md`、`AGENTS.md`、`docs/skills-audit-report.md`
4. 官方 Anthropic Skill 来源
5. `https://www.skills.sh/`
6. 使用 `skill-creator` 或手工创建项目专用 Skill

## 5. 安全边界

- 不安装来源不明、许可证不清、脚本混淆或要求上传凭证的 Skill。
- 不让外部 Skill 覆盖 Novel OS 的 source isolation、Context Builder、ReviewIssue、Runtime Policy、OS Envelope 和 GateResult 边界。
- 不让文件处理 Skill 在非文件任务中自动触发。
- 不让 `claude-api` 用于非 Anthropic provider 路线。
- 不让拆解类 Skill 的 raw source 进入正文生成链路。
- 不因使用或安装 Skill 跳过代码证据、测试和报告。

## 6. 后续建议

1. 后续每次外部 Skill 安装前，先将候选 Skill 写入本报告的待审条目。
2. 外部 Skill 若要进入根 `skills/`，必须记录许可证与再分发边界。
3. 对 runtime-only 官方 Skill 保持隔离，不用 `--prune` 清理，除非明确确认删除。
4. 若某类任务重复出现，再创建项目专用 Skill，而不是扩大通用 Skill 的触发范围。
