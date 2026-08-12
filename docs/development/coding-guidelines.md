# Coding guidelines

## Boundaries

- Keep one production execution plane and one PostgreSQL business authority.
- Make domain ownership visible in names and constructor dependencies.
- Use concrete, business-oriented queries and repositories.
- Keep composition roots declarative; they construct objects but do not query or mutate business state.
- Keep API routers and workers thin.
- Pass shared process resources once; do not hide global singletons or construct duplicate gateways.

## Abstraction

Introduce an interface when it protects a meaningful volatile boundary or supports multiple real implementations. Avoid speculative Factory/Registry/Facade/Adapter layers, one-method pass-through chains, duplicate DTOs, and generic repository frameworks. A larger cohesive module is preferable to dozens of shallow files.

Compatibility code requires a defined caller, retirement condition, classification, and architecture boundary. Migration-only code stays under `legacy_migration` and cannot become a production fallback.

## Transactions and effects

- Keep PostgreSQL transactions short and explicit.
- Preserve CAS, expected status/version, idempotency, trace, checkpoint, event, and outbox semantics.
- Do network I/O outside business transactions.
- Reconcile uncertain effects; never hide them with broad exception swallowing.
- Do not mutate another Authority's tables directly.

## Comments and documentation

Comments should explain invariants, authority/concurrency/recovery/temporal semantics, security, or a non-obvious reason. Remove comments that narrate the code, completed TODOs, temporary migration stories, and future speculation. Current documentation describes durable behavior; implementation reports and session logs do not belong in `docs/`.

## Verification

Run the smallest meaningful gate while changing code and the complete relevant gate before committing. Do not delete a failing test, lower an assertion, or replace a real dependency with a mock unless the production capability itself was intentionally retired and reachability evidence supports removal.
