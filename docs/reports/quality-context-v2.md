# Quality Context v2

Five Quality groups receive distinct governed views. Long-form state is represented
as `state_type -> entity_identity -> ordered rows`, preserving version, digest,
chapter, qualification and explicit-empty identity. `QualityContextBudgeter` uses a
replaceable estimator, removes only lower-priority facts, and fails closed if identity
or critical evidence cannot fit. `QualityContextCoverageReport` records selection,
entities, fact omissions, estimate, budget and repair status.

Source judges receive lineage and policy identities, never protected raw expression.
Evidence: `chapter_quality_authority/context_views.py`, unit tests and Chapter Saga
PostgreSQL proof. Commits `c410721`, `165d179`.
