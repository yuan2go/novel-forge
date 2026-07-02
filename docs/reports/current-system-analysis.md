# Current System Analysis

Date: 2026-07-02

## Summary

Novel Forge v6 is already an early Novel Operating System runtime rather than a prompt-only generator. It has schema-backed assets, local JSON storage, workflow runs, agent dispatch, trace/cost ledgers, review/rework, publish gate reports, continuity/KG preflight, draft versions, release packages, and a Next.js console.

The long-chain test shows that the runtime can produce and store many chapters, but the control layer was not strict enough for stable long-form production. The weak boundary was not prose generation. The weak boundary was canonical state, chapter-state persistence, structural repetition control, motif budgets, and publishing-time hard blocks.

## Relevant Code Boundaries

| Boundary | Current code | Role |
|---|---|---|
| Asset schemas | `src/novel_forge/schemas/` | Dataclass assets plus common validation. |
| Local storage | `src/novel_forge/storage/local.py` | JSON asset write/read, project-scope guard, KG dirty index. |
| Drafting | `src/novel_forge/modules/drafting/service.py` | Context, model call, draft asset, draft version, generation run. |
| Review | `src/novel_forge/modules/review/service.py` | Review report, quality/style/originality/chapter audit reports. |
| Revision | `src/novel_forge/modules/revision/service.py` | `review_issue -> revision_task -> editor_patch -> draft_version -> re-review -> publish_gate`. |
| Publishing gate | `src/novel_forge/modules/audit/service.py` | Chapter audit, publish gate report, release package. |
| Continuity/KG | `src/novel_forge/modules/continuity_graph/`, `src/novel_forge/modules/novel_kg/` | Graph snapshots, canon patch, continuity preflight. |
| Production versions | `src/novel_forge/modules/production_chain/service.py` | Outline/chapter-plan/draft versions and generation run evidence. |

## Gaps Found

The system had review and continuity assets, but no single hard long-form stability gate that could simultaneously enforce:

- forbidden aliases and canonical names;
- prose-only chapter text;
- mandatory chapter state;
- repeated chapter structure detection;
- motif budgets;
- arc question and payoff progress;
- foreshadowing lifecycle;
- character liability/debt tracking;
- villain action cadence;
- structured revision task generation for every gate failure.

## Implemented Direction

This iteration adds `src/novel_forge/modules/longform_stability/` and schema-backed assets for:

- `canon_database`
- `chapter_state`
- `chapter_pattern_report`
- `fact_ledger`
- `arc_plan`
- `foreshadowing_graph`
- `motif_budget_report`
- `character_state_ledger`
- `villain_operation_plan`
- P2 control reports for fatigue, style, platform, reward, and review-score gates

The new service is deterministic and testable. It is connected to draft generation and publish gate creation.
