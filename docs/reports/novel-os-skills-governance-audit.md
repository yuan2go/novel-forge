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
| Runtime drift 修复 | 已完成 | `make sync-skills-dry-run`、`make sync-skills`、`make check-skills` |
| Provider / Office 工具边界 | 已补齐 | `docs/09-skills/usage-policy.md`、`docs/09-skills/agent-skill-map.md` |
| 外部 writing Skill 吸收边界 | 已补齐 | `skill-governance`、`narrative-beat-design`、`project-planning`、`docs/skills-audit-report.md` |

## 3. 使用/安装记录

| Skill | 来源 | 本地路径 | 使用阶段 | 使用原因 | 风险 | 是否安装 | 是否同步 | 是否更新映射 |
| ----- | -- | ---- | ---- | ---- | -- | ---- | ---- | ------ |
| `skill-creator` | Claude Code system skill | `/Users/yuan/.codex-claude/skills/.system/skill-creator/SKILL.md` | Skill governance policy update | 按 Skill 最佳实践完善选择、安装、验证和记录策略 | 低；只读使用，无安装，无脚本执行 | 否，已存在 | 否 | 否 |
| `provider-runtime-policy` | project root skill | `skills/provider-runtime-policy/SKILL.md` | Novel OS acceptance completion | 约束 provider hard-stop、fallback、timeout、token/cost、model_call_log、cost_ledger | 中；影响模型运行治理，但无脚本 | 新增项目 Skill | 是，`make sync-skills` | 是 |
| `canon-continuity-graph` | project root skill | `skills/canon-continuity-graph/SKILL.md` | Novel OS acceptance completion | 约束 Canon Graph、continuity conflict、impact report、invalidation、rollback | 中；影响正典 gate，但无脚本 | 新增项目 Skill | 是，`make sync-skills` | 是 |
| `publish-release-gate-os` | project root skill | `skills/publish-release-gate-os/SKILL.md` | Novel OS acceptance completion | 约束 ReleasePackage、PublishGateReport、release readiness、rollback/resume | 中；影响发布 gate，但无脚本 | 新增项目 Skill | 是，`make sync-skills` | 是 |
| `claude-api` | runtime/vendor skill | `.claude/skills/claude-api/SKILL.md` | Runtime tool boundary policy | 明确只用于 Claude/Anthropic provider，不覆盖 OpenAI/Codex/provider-neutral 任务 | 高；provider 偏置、联网、credential 示例 | 否，已存在 | 否，runtime-only | 是，边界文档 |
| `docx` / `pdf` / `xlsx` | runtime/vendor skill | `.claude/skills/{docx,pdf,xlsx}/SKILL.md` | Runtime tool boundary policy | 明确专有许可、文件任务触发、Office/PDF/XLSX subprocess/network 边界 | 高；专有许可、文档来源泄漏、外部工具 | 否，已存在 | 否，runtime-only | 是，边界文档 |
| `writing-beats` | external personal skill | `/Users/yuan/.agents/skills/writing-beats/SKILL.md` | Narrative method review | 吸收 reader grounding、beat path、requires/grounds 方法到项目源 Skill | 中；外部个人 Skill，不作为项目 source of truth | 否 | 否，未 vendor | 是，改写进 `narrative-beat-design`、`chapter-outline`、`long-outline` |
| `writing-great-skills` | external personal skill | `/Users/yuan/.agents/skills/writing-great-skills/SKILL.md` | Skill governance review | 吸收 predictable、single source of truth、progressive disclosure 治理原则 | 中；外部个人 Skill，不作为项目 source of truth | 否 | 否，未 vendor | 是，改写进 `skill-governance`、`usage-policy` |
| `writing-plans` | external personal skill | `/Users/yuan/.agents/skills/writing-plans/SKILL.md` | Planning method review | 吸收文件结构、接口依赖、测试命令、回滚边界等工程计划格式 | 中；外部个人 Skill，不作为项目 source of truth | 否 | 否，未 vendor | 是，改写进 `project-planning` |
| `writing-fragments` / `writing-shape` | external personal skill | `/Users/yuan/.agents/skills/{writing-fragments,writing-shape}/SKILL.md` | External writing skill review | 判定为个人写作探索/成文流程，暂不进入 Novel OS 项目源 Skill | 中；与项目生产资产边界不直接匹配 | 否 | 否，保留外部 | 否 |

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
- 不让 model provider failure silent fallback；生产模型调用必须满足 `provider-runtime-policy`。
- 不让 canon mutation 或 release package 绕过 `canon-continuity-graph`、`review-issue-gate` 和 `publish-release-gate-os`。
- 不直接 vendor 外部个人 writing Skill；只在许可证和边界清楚时吸收方法，并重写为项目术语、schema、gate 和 runtime contract。
- 不让拆解类 Skill 的 raw source 进入正文生成链路。
- 不因使用或安装 Skill 跳过代码证据、测试和报告。

## 6. 后续建议

1. 后续每次外部 Skill 安装前，先将候选 Skill 写入本报告的待审条目。
2. 外部 Skill 若要进入根 `skills/`，必须记录许可证与再分发边界。
3. 对 runtime-only 官方 Skill 保持隔离，不用 `--prune` 清理，除非明确确认删除。
4. 若某类任务重复出现，再创建项目专用 Skill，而不是扩大通用 Skill 的触发范围。
5. Skill 变更后必须保持 `make check-skills` 通过，避免 `.claude/skills` runtime copy 再次漂移。
6. `writing-fragments`、`writing-shape` 暂时保持外部个人写作 Skill；若后续要进入项目源，需先通过 `skill-governance` 做 license、trigger、schema 和 gate 审查。
