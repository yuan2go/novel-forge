# Quality Gates

## Gate Policy

Novel OS quality gates are hard operating boundaries, not advisory prose.

Gate statuses:

- `ready`: may become release-ready.
- `needs_revision`: may be revised but not published.
- `blocked`: must not become canonical/release-ready.

## Publishing Gate Checks

Current publishing gate includes:

1. Chapter audit.
2. Quality report presence.
3. Style report presence.
4. Originality report presence.
5. RAG quality report.
6. Stability preflight.
7. Platform compliance.
8. Semantic review.
9. Long-form stability:
   - canon consistency;
   - output sanitizer;
   - chapter state;
   - fact ledger;
   - pattern similarity;
   - motif budget;
   - arc progress;
   - foreshadowing graph;
   - character/debt state;
   - villain operation;
   - review score.

## OS Acceptance Gate

Long-form production readiness is also checked by:

```text
POST /product/longform-stability/acceptance
```

This writes a `gate_result` when `persist=true`. It is deeper than a single chapter Publishing Gate because it checks project-level evidence coverage:

- every draft has state/pattern/fact/motif/character/foreshadow/villain evidence;
- Publishing Gate includes long-form results;
- failed gates produce revision tasks;
- model-assisted extraction has model/cost ledger evidence when used;
- workflow/agent runtime evidence exists for OS-level acceptance.

## Model-Assisted Extraction Rule

Model assistance is allowed only as a bounded extraction helper:

- deterministic extraction remains the required fallback;
- model calls must go through ModelRouter/runtime ledger;
- model output cannot become canonical without schema-backed long-form artifacts;
- model-assisted extraction cannot override Publishing Gate fail results.

## Provider Hard-stop Gate

Provider guard proof is not counted from configuration alone. A hard-stop dimension is covered only when a `provider_runtime_guard` gate records the actual triggered dimension.

Required dimensions:

- token over budget;
- cost over budget;
- timeout;
- cancel / streaming cancel;
- provider error with failed model call;
- retry exhaustion into retry/dead-letter state.

Failed provider calls must not write accepted drafts, ready release packages, or canonical chapters.

## OS Surface Coverage Gate

Strict Novel OS production paths must be visible in:

```text
GET /product/runtime/policy/surface-coverage
```

The operator matrix distinguishes:

- `enforced`: model or release path has OS envelope and required gate boundary;
- `compatible`: deterministic/manual/ops path is schema/audit bounded and does not publish canonical text;
- `blocked`: path can bypass the OS boundary;
- `needs_fix`: path has registered intent but lacks required enforcement.

## Agent Center Gate

Agent Center readiness requires evidence for:

- run graph;
- gate timeline;
- checkpoints;
- budget burn;
- retry controls;
- dead-letter queue;
- rollback preview;
- SLA/duration tracking;
- evidence drawer;
- operation coverage.

The cockpit endpoint is:

```text
GET /product/agents/center
```

## Fail Handling

Every failed long-form gate issue becomes a structured revision task issue:

```json
{
  "dimension": "output_sanitizer",
  "severity": "high",
  "message": "chapter body contains forbidden metadata",
  "recommendation": "remove prompt/metadata wrappers before storage",
  "status": "open"
}
```

## Canonical Chapter Rule

A chapter cannot be considered canonical if:

- sanitizer status is fail;
- canon check has forbidden alias;
- chapter state is missing;
- repeated pattern fail occurs;
- arc/foreshadow/motif gates block;
- publish gate decision is not `ready`.

## Testing

Required tests:

- unit tests for each deterministic checker;
- integration test for publish gate -> revision task;
- end-to-end test for draft -> artifacts -> gate -> release package blocked/ready states;
- admin API/UI contract tests for long-form dashboard, extraction, and OS acceptance endpoints.
