# Authority model

An Authority is the single component allowed to decide and persist a class of business truth. PostgreSQL stores that truth; an application or coordinator does not become an Authority merely because it can open a database transaction.

## Mutation rule

```text
API / Worker / Supervisor
          │
          ├── read → concrete business query projection
          │
          └── write → Domain Authority command
                           │
                           ▼
                 transaction + CAS + event/outbox
```

Production routers, workers, supervisors, and composition roots must not mutate business tables directly. Repositories may be concrete and domain-specific; the project does not use a generic repository framework. Boundaries follow business actions such as “advance Book supervisor checkpoint” or “activate a plan”, not individual tables.

## PostgreSQL ownership

`AuthorityUnitOfWork` provides one transaction and a repository set. Domain Authorities use it to keep state, versions, operation evidence, asset bindings, and outbox records atomic. Connection pooling, session timeouts, role budgets, retry classification, and shutdown belong to `DatabaseRuntime`.

Automatic database retries are limited to explicitly replay-safe transactions. Provider calls and object-store transfers occur outside business transactions and are reconciled through ExternalEffect records.

## Reads

Read services may join multiple authority projections when the query has a stable business meaning. Examples include Book coordination candidates, accepted Chapter evidence, and as-of narrative state. A read model:

- never activates or supersedes an asset;
- never advances a business state machine;
- reports missing or stale evidence explicitly;
- preserves project/workspace and accepted-chapter boundaries.

## Candidate versus authority

Story Design generation, Agent reasoning, quality evaluation, reader outcomes, and source analysis produce candidates, evidence, decisions, or proposals. They cannot directly mutate Canon, StoryState, an active typed plan, or a Book/Chapter state. The owning Authority validates and commits the result.

## Enforced boundaries

Architecture manifests and fitness tests enforce domain import direction, direct provider-call allowlists, migration-only Legacy isolation, Chapter execution ownership, Book SQL boundaries, and retired compatibility paths. See `architecture/manifests/fitness-policy.yaml` and `tests/architecture/`.
