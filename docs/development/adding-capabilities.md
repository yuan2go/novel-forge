# Adding capabilities

Add behavior to the existing Authority and execution planes. A new business capability does not justify a new scheduler, provider gateway, Attempt model, LocalStorage authority, or compatibility runtime.

## Decide ownership first

Identify:

- the Domain Authority that can accept the output;
- whether the operation is an inline atomic command, durable job, or saga;
- the immutable input/output asset contracts;
- idempotency, trace, approval, recovery, and compensation requirements;
- the concrete query needed by coordinators or operators;
- whether an external effect is involved.

If no Authority owns the decision, define that boundary before writing a worker.

## Reuse the production execution plane

Provider and object-store work must use `ProductionExecutionComposition` and current PEP contracts. Add a governed capability/route and explicit port as needed; do not borrow a peer application's internals. The Domain Authority validates and commits the returned candidate.

## Wire the current runtime

For a genuinely production-reachable operation:

1. define and test the operation contract;
2. implement the Authority command/handler and concrete reads;
3. compose it from the API or correct worker root;
4. add it to the production-entry or worker manifest;
5. add architecture fitness when a new boundary must remain true;
6. add unit, acceptance, and dependency-backed integration evidence appropriate to risk;
7. update current docs without claiming a higher proof level.

Do not add manifest entries for fixture-only helpers. Do not bypass Command Kernel admission for a durable operation merely because a router can call a repository directly.

## Capability Packs and Skills

A Capability Pack freezes workflow nodes, capability contracts, prompt/tool/context policies, gates, and Skill bindings by version and hash. A Skill is a reusable procedure, not an alternate runtime. Changes to repository Skills use `skills/` as the source and `make sync-skills`; runtime copies are generated.
