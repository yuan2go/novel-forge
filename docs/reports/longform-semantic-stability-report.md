# Long-form Semantic Stability Report

Commit: `235b96a`; Authority bindings: `5aa2a89`.

Implemented reports: MotivationDrift, EntityMergeProposal, ForeshadowPayoff, WorldRuleConflict, PowerConflict, PatternRepetition/TropeFatigue, NarrativeDebt/ArcProgress, and enhanced LongformRecap. They distinguish event-driven growth from unsupported drift, require evidence/confidence for aliases, score payoff causality/memory/consequence, model power conditions/costs rather than only numbers, fingerprint narrative mechanisms, and age debt against payoff windows.

`run_longform_recap` optionally consumes the complete semantic report set and records main-plot, motivation, relationship, canon/world/power, foreshadow/promise/reward/antagonist, pattern/theme/quality, next-window constraints and review focus. Its policy explicitly forbids rewriting accepted chapters.

Tests: `test_longform_semantic_domain` (6) and existing `test_longform_recap_agent` (4), all passed. This is deterministic fixture proof; no 10/30/100-chapter real-provider validation was run.
