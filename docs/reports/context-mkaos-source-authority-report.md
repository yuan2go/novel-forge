# Context, MKAOS, and Source Authority Report

Commit evidence: `8fdb326`, `9d49479`, `759ada0`, `bae6f10`.

- ContextBundle is immutable Authority output and freezes project/stage/profile, planning/canon/character/foreshadow/promise/reward/style/knowledge/material/source-policy versions, selection/rejection evidence, token budget, digest, source isolation, invalidation keys, and creating Operation.
- Twelve Context Profiles fail closed by asset type, project, qualification, governance, source use mode, risk, required inputs, and token budget. Draft rejects raw, review-only, structure-only, stale, revoked, quarantined, and cross-project candidates.
- MKAOS selection scores semantic relevance, stage/genre/narrative fit, trust/risk, usage, quality, freshness, redundancy, conflict, and project specificity; every selected/rejected version carries reasons and score components.
- Source eligibility consumes SourcePolicy, LicenseCheck, RiskReport, and Snapshot versions. Unsafe inputs downgrade to structure/review-only or become stale/quarantined/revoked; production Context still rejects them.
- Git, RSS, and public-domain connector contracts are allowlisted, bounded, approval-aware, no-network-by-default ExternalEffect intents. Deterministic adapters enforce size/type/license/robots/ToS/injection/checksum/receipt/diff/invalidation without persisting raw content.
- ChangeImpactReport and RegenerationPlan never mutate accepted prose, canon, outline, or character core.

Focused evidence: `test_context_authority_domain`, `test_mkaos_authority_selection`, `test_source_eligibility_domain`, `test_source_connectors`, and the existing 30-test source-intake suite. Real network connector execution was not run.
