# Skill Usage Policy

## Module Goal

This document defines how Novel Forge uses project Skills without turning them into an ungoverned prompt library. Skills are reusable methods; production state still belongs to schema-backed assets, Context Builder, Runtime Policy, ReviewIssue, gates, audit, and tests.

## Skill Selection

Before each substantial phase, perform Skill Discovery instead of hard-coding a fixed Skill list.

Discovery order:

1. Check root project Skills under `skills/`.
2. Check runtime Skills under `.claude/skills/`.
3. Check `docs/09-skills/agent-skill-map.md`, `AGENTS.md`, and `docs/skills-audit-report.md`.
4. Check official Anthropic Skill sources when local coverage is insufficient.
5. If necessary, search trusted external sources such as `https://www.skills.sh/`.
6. If no appropriate Skill exists, use `skill-creator` or manually create a project-specific Skill under root `skills/`.

Selection criteria:

- direct relevance to the task;
- fit with Novel OS / novel-forge engineering goals;
- provider-route compatibility;
- scripts, subprocess, browser, LibreOffice, server, API key, or external network behavior;
- license and redistribution risk;
- clear trigger boundary;
- presence of `SKILL.md`, README, LICENSE, scripts, and reference material;
- ability to verify locally.

Prefer the smallest set of Skills that covers the task. If the task affects production assets, use a Skill with a Novel OS Runtime Contract or pair the creative Skill with one of:

   - `mkaos-knowledge-asset-os`
   - `context-builder-source-isolation`
   - `review-issue-gate`
   - `agent-loop-governance`
   - `provider-runtime-policy`
   - `canon-continuity-graph`
   - `publish-release-gate-os`
   - `narrative-beat-design`
   - `platform-strategy-os`
   - `novel-os-engineering-audit`

If the task changes Skills, Skill routing, runtime sync, external Skill adoption, or vendor/tool boundaries, use `skill-governance`.

At the beginning of each substantial phase, emit this audit note:

```text
Skill selection:
- Task:
- Candidate skills:
- Selected skills:
- Reason:
- Install needed:
- Risk:
```

## Runtime Contract

Production-relevant Skill outputs must be:

- schema-backed;
- traceable to input refs, `project_id`, and, when applicable, `trace_id`;
- source-isolated;
- gate-aware;
- compatible with Context Builder and Knowledge Pack contracts;
- reviewable through ReviewIssue / GateResult when risks are found.

Markdown output is acceptable for operator handoff, audit reports, and planning docs. It is not sufficient for production generation, revision, publishing, feedback learning, or knowledge mutation unless it is also mapped to an asset schema or documented target path.

## Source Isolation

Skills may use reference works only for abstract structural learning:

- structure;
- rhythm;
- conflict mechanism;
- character mechanism;
- emotion curve;
- hook pattern;
- craft technique;
- review criteria.

Skills must not place these into generated prose, publish packages, recap context, or feedback backflow:

- raw source text;
- `source_chunk.raw_text`;
- parallel pair `source_text` or `target_text`;
- protected quotes;
- distinctive expressions;
- source-specific character, setting, scene, or plot combinations.

## License Boundary

- Root `skills/` contains project-owned Skill instructions unless a file explicitly says otherwise.
- `.claude/skills/` is runtime output and may include official/tool Skills from external sources. Those Skills keep their original upstream license and should not be copied into root `skills/` without review.
- External Skill adoption must record source URL, commit/version when available, license, scripts, dependencies, network behavior, install command, install path, and verification result.
- Reject or mark manual-review for Skills with unknown binaries, unsafe scripts, hidden network calls, credential handling, or incompatible licenses.
- External writing/process Skills should be absorbed as Novel OS methods only after rewriting them into project terminology, schema boundaries, and gate requirements; do not directly vendor personal workflow Skills into root `skills/`.

## External Skill Installation

External Skill installation is allowed only when local Skills cannot reasonably cover the task.

Before installing, inspect and record:

1. Skill page or repository summary.
2. Source and maintainer.
3. Install command.
4. License.
5. `SKILL.md`.
6. README/reference files when relevant.
7. Scripts and dependencies.
8. External API key requirements.
9. Browser, server, CLI, subprocess, LibreOffice, or system-modifying behavior.
10. Whether the Skill may change project code, config, runtime state, or system environment.
11. Why project-level or runtime-level installation is justified.

Allowed install commands include:

```bash
npx skills add <skill-source>
npx skills add <skill-source> --skill <skill-name>
npx skills add https://github.com/anthropics/skills --skill <skill-name>
```

After installing, verify:

```bash
test -f ".claude/skills/<skill-name>/SKILL.md"
```

Then update:

- `docs/reports/novel-os-skills-installation-check.md`
- `docs/reports/novel-os-skills-governance-audit.md`
- `docs/09-skills/agent-skill-map.md` when the Skill changes Agent routing.

Do not install:

- unknown-source Skills;
- obfuscated scripts;
- Skills that request uploading secrets, tokens, cookies, or private config;
- system-level configuration modifiers;
- auto-networking scrapers with unclear scope;
- Skills that conflict with the project provider route;
- broad bundles unrelated to the task;
- unclear-license Skills that may contaminate the repository.

## Provider And Network Boundary

- Real model providers, browsers, MCP servers, platform APIs, office-file conversion tools, and external data sources are opt-in.
- Default tests must use deterministic local fixtures or mock providers.
- Provider failure must not silently downgrade production output.
- Tool Skills can help with setup or testing, but they do not bypass Runtime Policy, OS Envelope, Audit Log, or ReviewIssue gates.

### `claude-api` Boundary

- Use `claude-api` only for explicit Claude/Anthropic provider work, Claude SDK migration, Claude model selection, Managed Agents, Claude tool use, or Anthropic API debugging.
- Do not use `claude-api` for OpenAI, Codex, Gemini, local-provider, provider-neutral, or repository-default LLM tasks.
- If provider is ambiguous, inspect the target code for provider markers before using `claude-api`; ask or use provider-neutral project policy when unclear.
- `claude-api` examples do not authorize live provider calls. Production model calls must satisfy `provider-runtime-policy`, `model_call_log`, `cost_ledger`, budget, timeout, and fallback requirements.
- Never write API keys, OAuth tokens, cookies, bearer tokens, federation secrets, or provider credentials into code, docs, logs, reports, or Skill output.

### Office / PDF / XLSX Runtime Skill Boundary

- `docx`, `pdf`, and `xlsx` are runtime/vendor tool Skills for explicit file tasks only.
- Their LICENSE files include proprietary service restrictions; do not copy them into root `skills/`, publish them, or treat them as project-owned source Skills without license review.
- Running LibreOffice, pandoc, OCR, PDF tools, spreadsheet recalculation, browser previews, npm packages, or Python helpers is opt-in and must be tied to a concrete file task.
- Extracted document text is still source material. It must not enter MKAOS packs, ContextBundle, prose, publish, recap, or feedback backflow unless source isolation, rights policy, and ReviewIssue gates allow the abstracted result.
- Office/PDF/XLSX scripts are not default validation dependencies. Project tests should not require them unless the task explicitly targets those formats.

## Runtime Copy Boundary

- Root `skills/` is source of truth.
- `.claude/skills/` is generated runtime copy and must not be hand-edited.
- Use `make sync-skills-dry-run` before runtime sync.
- Use `make sync-skills` only when intentionally updating local Claude Code runtime copies.
- Use `--prune` only after confirming extra runtime-only Skills should be removed.
- Use `skill-governance` before pruning, vendoring, or reclassifying runtime-only Skills.

## Usage And Installation Record

After each Skill use, install, sync, or creation, update the governance reports with this table shape:

| Skill | 来源 | 本地路径 | 使用阶段 | 使用原因 | 风险 | 是否安装 | 是否同步 | 是否更新映射 |
| ----- | -- | ---- | ---- | ---- | -- | ---- | ---- | ------ |

If no external Skill was installed, record `否` under installation and the reason local Skills were sufficient.

## Acceptance

- New or changed Skills have frontmatter with `name` and `description`.
- New or changed Skills include required sections: use cases, inputs, workflow, output, quality, forbidden behavior, module relationships.
- Production-relevant Skills include Novel OS Runtime Contract.
- Skill changes are validated with at least `make sync-skills-dry-run` and `git diff --check`.
