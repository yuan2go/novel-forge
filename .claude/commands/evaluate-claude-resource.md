# Evaluate Claude Resource

Use this command when reviewing a third-party Claude Code resource before importing ideas, commands, hooks, Skills, agents, scripts, or automation into Novel Forge.

This is a static, read-only review command. Do not run the target repository, install dependencies, enable hooks, execute scripts, copy secrets, or modify local runtime configuration during the review.

## Input

Provide one repository URL, file path, or resource description.

```text
$ARGUMENTS
```

If no argument is provided, evaluate the current repository's Claude Code execution surfaces.

## Review Scope

Check the resource as a Claude Code execution dependency, not only as documentation.

Focus on:

- Skills and reusable prompt instructions.
- Slash commands and command templates.
- Hooks or lifecycle automation.
- Agent orchestrators and delegation rules.
- Scripts or tools invoked by commands.
- Persistent state files that influence future behavior.
- Network, filesystem, credential, or shell execution surfaces.

## Required Checks

### 1. Fit For Novel Forge

Decide whether the resource supports one of these project needs:

- Writing-system governance.
- Skill quality and runtime sync.
- Agent routing and role boundaries.
- Static review and safety gates.
- Documentation generation or validation.
- Local deterministic tooling.

Reject resources that mainly add unrelated web platforms, telemetry, hidden network calls, generic productivity tricks, or automatic code execution.

### 2. Safety And Trust Boundary

Identify:

- Whether hooks run implicitly.
- Whether commands invoke shell scripts.
- Whether scripts read or write outside the repository.
- Whether any step requires secrets, tokens, external APIs, or elevated permissions.
- Whether persistent files can change future agent behavior.
- Whether disable, dry-run, or check-only modes exist.

Prefer explicit uncertainty over unsupported confidence.

### 3. Documentation Match

Compare declared behavior with observable behavior.

Flag:

- Undocumented side effects.
- Claims not supported by visible files.
- Missing installation or removal instructions.
- Missing tests for execution surfaces.
- Ambiguous permissions.

### 4. Import Decision

Choose one decision:

- `adopt`: safe and directly useful.
- `adapt`: useful pattern, but must be rewritten for Novel Forge.
- `defer`: useful later, not needed now.
- `reject`: unsafe, irrelevant, or too costly.

For `adopt` or `adapt`, specify the smallest local change.

## Output Format

```markdown
# Claude Resource Evaluation

## Resource

## Summary

## Fit For Novel Forge

## Execution Surfaces

## Safety Risks

## Documentation Gaps

## Import Decision

## Minimal Local Change

## Required Tests Or Checks

## Open Questions
```

## Novel Forge Boundaries

- Do not import hooks by default.
- Do not import resources that store protected fiction content inside Skills.
- Do not add external dependencies without an explicit current-doc decision and tests.
- Do not change `.claude/skills/` directly; sync from root `skills/`.
- Do not enable automatic shell/network behavior without explicit review.
