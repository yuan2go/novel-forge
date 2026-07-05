# V7 Content Intelligence Document Index

Updated: 2026-07-05
Branch: `feat/v7-content-intelligence-and-longform-proof`

This index collects the active v7 content-intelligence design documents for the next implementation pass.

## Active Documents

| Document | Purpose |
|---|---|
| [v7-content-intelligence-current-analysis.md](v7-content-intelligence-current-analysis.md) | Code-grounded gap analysis for the current v7 branch. |
| [v7-content-intelligence-product-spec.md](v7-content-intelligence-product-spec.md) | Product requirements, workflows, acceptance criteria, and release criteria. |
| [v7-content-intelligence-architecture.md](v7-content-intelligence-architecture.md) | Module architecture, asset schema design, API design, Context Builder integration, Agent/Workflow operation contracts, gate semantics, and test strategy. |
| [v7-claude-code-next-development-prompt.md](v7-claude-code-next-development-prompt.md) | Execution prompt for the next Claude Code implementation cycle. |

## Recommended Reading Order

1. `CLAUDE.md`
2. `AGENTS.md`
3. `docs/README.md`
4. `docs/project-current-state.md`
5. `docs/roadmap/current-roadmap.md`
6. `docs/architecture/novel-operating-system-new-capabilities.md`
7. `docs/new/v7-content-intelligence-current-analysis.md`
8. `docs/new/v7-content-intelligence-product-spec.md`
9. `docs/new/v7-content-intelligence-architecture.md`
10. `docs/new/v7-claude-code-next-development-prompt.md`

## Implementation Scope

The next implementation pass should focus on:

1. Genre OS.
2. Style OS.
3. Canon Graph 2.0 genre-specific reasoning.
4. Quality Eval 2.0.
5. Long-chain Proof Center.
6. Publishing / Feedback Adapter 2.0.
7. Agent and Workflow operation coverage for the new content-intelligence layer.

## Boundary

Do not create a parallel generation pipeline. All new work must reuse the existing Novel OS runtime: Context Builder, MKAOS, Canon/KG, Long Memory, Agent Scheduler, Loop Kernel, ReviewIssue, Evaluation Gate, Publish Gate, provider runtime policy, Trace, Cost Ledger, and schema-backed assets.
