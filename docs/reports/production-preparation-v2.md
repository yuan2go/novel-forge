# Production Preparation v2

Date: 2026-07-18.

`ProductionPreparationService` now emits an immutable, versioned
`ProductionInputManifest` rather than choosing one latest asset per type. It records
selected/rejected versions, entity scopes, reasons, qualification/source evidence,
profile versions, token/provider budgets, risks, approvals, and a deterministic
digest.

Collection inputs support multiple CharacterState, RelationshipState, knowledge,
material, promise, reward, rule, and foreshadow assets. Chapter 2+ requires all nine
previous-state families, including RelationshipState; an absent family needs an
explicit `EmptyStateDeclaration`.

Distinct Stage Profiles enforce stage-specific allowed/required/forbidden types, evidence-only rendering,
raw-source exclusion, token budgets, and copyright policy. Quality and Platform
profiles resolve to eligible AssetVersions and flow through Manifest, Context,
Quality, and Publish lineage.

Checklist and approval assets are frozen as evidence-only Context Segments. They
are not rendered into the model-visible Stage Context View. Context Completion now
requires `ContextManifestConsistencyReport`, proving:

`Manifest selected versions == frozen Operation inputs == Context segments`.

Blanket per-chapter approval was removed. Preparation requests approval only for a
matching risk scope, target versions, chapter, and expiry.

Collection candidates are also filtered by stage scope, chapter range, ChapterPlan
cast/entity scope, and relationship-pair scope. The authoritative ChapterPlan
Operation replaces the provisional creator identity and recomputes the full Manifest
digest before materialization.

Evidence: commits `35addd2`, `c60d36a`; unit Preparation/Context tests and PostgreSQL prepared
chapter Saga tests. Maturity is `integration_proven` with fixtures, not Provider or
long-form proof.
