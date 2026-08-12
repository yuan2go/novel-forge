---
name: skill-governance
description: Use when creating, revising, auditing, syncing, pruning, or adopting Novel Forge project Skills so each Skill remains predictable, single-source-of-truth, progressively disclosed, trigger-safe, license-safe, and aligned with Novel OS runtime boundaries.
---

# Skill Governance

## Novel OS Runtime Contract

- 项目源 Skill 必须维护在 root `skills/`，`.claude/skills/` 只能由 sync 生成或保留 runtime/vendor 工具 Skill。
- 生产相关 Skill 必须包含 Novel OS Runtime Contract，并明确 schema-backed output、Context Builder、Knowledge Pack、ReviewIssue、GateResult、source isolation 和 traceability。
- 外部 Skill 不得直接进入 root `skills/`，除非记录 source、license、scripts、dependencies、network/provider behavior 和 verification。
- Skill 治理只更新仍有长期价值的最小文件：root Skill、`AGENTS.md` 或 `docs/development/skills.md`。不要生成 session-level 审计报告。

## 适用场景

- 新建或更新 project Skill。
- 审计 Skill 是否可预测、触发清晰、无重复、无 runtime drift。
- 判断外部 Skill 是否能 vendor、应改写吸收，还是只保留为 runtime-only。
- 调整 Skill Map、同步 `.claude/skills`、处理许可证或外部工具边界。

## 输入要求

- 目标 Skill 名称、任务上下文、相关 Agent、已有 `skills/<name>/SKILL.md`。
- 外部来源时需提供 source path/URL、license、scripts、references、dependencies、network/provider behavior。
- 相关 docs：`AGENTS.md`、`docs/development/skills.md`。

## 操作流程

1. 明确 invocation：这个 Skill 是否需要 agent 自动触发，还是只该留在文档/外部个人工具中。
2. 检查 description：只写真实触发分支，避免泛化抢占其他 Skill。
3. 检查 single source of truth：同一规则只放一处；其他文件只引用或总结。
4. 检查 progressive disclosure：核心步骤放 `SKILL.md`，长 reference 才拆文件；不要为短 Skill 加无用资源。
5. 检查 predictability：每个流程有可检查完成条件，避免“写得更好”这类不可验收目标。
6. 检查 Novel OS boundary：schema、gate、trace、source isolation、provider/runtime、copyright 是否完整。
7. 更新 root Skill 和最小必要的长期规则文件；再执行 sync dry-run、sync、check。

## 输出格式

```markdown
# Skill Governance Report

## Decision
- skill:
- action:
- source:
- license:

## Trigger Boundary
- model-invoked:
- overlaps:
- protected routes:

## Runtime Boundary
- schema:
- source isolation:
- gate:
- sync:

## Verification
- quick validate:
- sync dry-run:
- check-skills:
- diff check:
```

## 质量标准

- Skill 必须短而可执行，优先流程和边界，少写泛泛理论。
- 每个项目 Skill 只能有一个 canonical root copy。
- 外部 Skill 方法论应改写为 Novel OS 语境，不直接复制不明许可证内容。
- Skill 更新后必须能通过 frontmatter 校验、`make sync-skills-dry-run`、`make check-skills` 和 `git diff --check`。

## 禁止事项

- 禁止直接手工编辑 `.claude/skills` 作为源。
- 禁止把外部 Skill 原样 vendor 到 root `skills/` 而不做许可证和边界审查。
- 禁止创建与既有 Skill 触发重叠但职责不清的新 Skill。
- 禁止让 Skill 绕过 AGENTS.md、schema validation、Runtime Policy、ReviewIssue 或 gate。

## 与其他模块的关系

- 上游：Skill audit、external Skill intake、Agent-Skill map、usage policy。
- 下游：root `skills/`、`.claude/skills` runtime copy、Agent routing。
- Agent：Engineering Agent、Quality Agent、Chief Editor Agent。
