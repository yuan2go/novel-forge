# Skills

An Agent is a role and permission boundary; a Skill is a reusable, versioned procedure. Skills never bypass Authority, schema, copyright, provider, storage, or quality gates.

## Repository source of truth

Authoritative Skill sources live in `skills/`. Runtime copies under `.claude/skills/` are generated:

```bash
make sync-skills-dry-run
make sync-skills
make check-skills
```

Do not hand-edit `.claude/skills/` as the source. A Skill change requires validation or an appropriate dry run and drift check.

## Runtime binding

Capability Pack manifests bind Skills by reference, version, content hash, input/output contracts, invocation limit, dependency graph, and drift policy. A Skill describes how a capability is performed; it does not create a second operation lifecycle or confer business commit authority.

The Unified Agent Harness freezes the discoverable Skill catalog at admission.
Activation is explicit and records Skill id/version/hash, catalog hash, caller
or model origin, reason and transcript lineage. `skill.activate` is a
Harness-native metadata action: it grants no Tool permission, Authority
permission or hidden capability outside the frozen Pack.

## Agent selection

Use the Agent/Skill map in `AGENTS.md` to choose procedures for a bounded task. Production Agent execution additionally requires an active Agent definition, qualified capability mapping, frozen runtime contract, allowed tools/context, budgets, and an accepting Domain Authority.

## Source and copyright boundary

Skills analyzing reference works may extract abstract structure, rhythm, conflict mechanisms, craft, and checks. They may not transfer protected expression, characters, settings, or plot combinations into generated drafts. Source-derived assets preserve lineage and remain abstract.
