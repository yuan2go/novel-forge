# V5 Open Issues

| ID | Issue | Severity | Status | Recommendation |
|---|---|---|---|---|
| V5-OI-001 | Real model adapters have contract skeletons but no external API implementation. | medium | partially resolved | Claude Code now has manual handoff packets, but not automated model calls. Add provider implementations only after ADR, dependency policy, and secret policy. |
| V5-OI-002 | Validation is structural, not full semantic schema validation. | medium | partially resolved | Added deterministic semantic validators for feedback insight, workspace state, and review comparison shapes; Pydantic remains deferred. |
| V5-OI-003 | Module packages now have service entry points, but domain logic is still basic/mock-level. | low | partially resolved | Continue adding richer module internals only after status/logging P0 work is stable. |
| V5-OI-004 | Local retrieval is hybrid hash-vector plus BM25, but no real semantic embedding model or vector database yet. | low | partially resolved | Keep hybrid local retrieval for offline tests; add real embeddings/vector database only after ADR, dependency, and cost policy. |
| V5-OI-005 | Runtime Skill copies can drift if edited manually. | low | partially resolved | Added `make check-skills` and `scripts/sync_claude_skills.py --check` to detect drift; root `skills/` remains source of truth. |
| V5-OI-006 | Demo output can accumulate duplicate random assets across repeated runs. | medium | resolved | `V5-OPT-P0-005` adds summary-based clean sample runs. |
| V5-OI-007 | Pipeline now records task/run status, but run logs and recovery instructions are not yet implemented. | medium | resolved | `V5-OPT-P0-004` adds run logs, recovery instructions, and recovery notes. |
| V5-OI-008 | Review comparison exists, but reviewers are deterministic local mocks. | low | partially resolved | Replace or supplement mock profiles only after real model adapter policy is approved. |
| V5-OI-009 | Workspace state exists, but cross-book canon reconciliation is still basic. | medium | partially resolved | Workspace now supports series/book identifiers and multi-book tests; add cross-book conflict detection in a later pass. |
| V5-OI-010 | Feedback trend analysis includes statistics but is still deterministic and small-sample sensitive. | low | partially resolved | Keep deterministic metrics for tests; add model-assisted or larger-cohort statistical analysis after feedback volume grows. |
| V5-OI-011 | External Claude Code resources could introduce implicit hooks, shell commands, or trust-boundary drift if copied directly. | medium | partially resolved | Use `.claude/commands/evaluate-claude-resource.md` and `docs/09-skills/external-resource-intake.md`; keep hooks/plugins deferred until ADR and tests exist. |
| V5-OI-012 | Local JSON storage now has locks, backups, and SQLite manifest, but no production database or distributed concurrency model. | medium | partially resolved | Keep JSON+SQLite for local V5 testing; evaluate Postgres/Qdrant/queue stack by ADR before multi-user production. |
| V5-OI-013 | Creative quality gates are deterministic and local. | medium | partially resolved | Use local gates as minimum guardrail; add model-assisted and corpus-calibrated gates after real provider policy is approved. |
