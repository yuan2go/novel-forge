# Novel OS v6 Hardening Architecture

## Scope

v6 hardening is about fail-closed production operation, not adding another prompt layer.

The hardened runtime now exposes four operator proof surfaces:

1. OS surface coverage: `/product/runtime/policy/surface-coverage`
2. Provider hard-stop evidence: `/product/runtime/provider-hard-stop-evidence`
3. Agent Center snapshot: `/product/agents/center`
4. Longform stability control and calibration: `/product/longform-stability/*`

## Enforcement Boundary

Model-producing paths must use the OS envelope:

- runtime policy registration;
- trace span;
- model call log;
- cost ledger;
- provider runtime guard;
- required gates for the operation.

Production chapter release paths must additionally pass Publishing Gate. A blocked publish gate can create revision tasks and blocked release packages, but it must not create a ready canonical chapter.

## Provider Hard-stop

Provider runtime guard now tracks explicit hard-stop dimensions:

- token cutoff;
- cost cutoff;
- timeout;
- cancel / streaming cancel.

Each dimension has a triggered flag in gate evidence. The provider evidence report only counts dimensions that actually failed closed; configured but untriggered limits do not count as proof.

Provider failures must write:

- `gate_result` with `gate_kind=provider_runtime_guard`;
- failed `model_call_log`;
- trace span;
- agent failure report when running through `GuardedModelAdapter`;
- retry/dead-letter state when routed through Agent Scheduler.

## Agent Center

`agent_center_snapshot` is the backend contract for the evidence cockpit.

It aggregates:

- run graph;
- gate timeline;
- checkpoint list;
- budget burn;
- retry controls;
- dead-letter queue;
- rollback preview;
- SLA/duration rows;
- evidence drawer;
- operation coverage.

The Admin page `/agent-dispatch` renders these fields directly and keeps scheduler controls and recovery actions in the same cockpit.

## Longform Control Console

`/longform-stability` is now an editable OS console, not only a evidence dashboard.

Supported control asset writes:

- Canon Database;
- Arc Planner;
- Foreshadowing Graph;
- Character State / Debt Ledger;
- Villain Operation Model.

Calibration writes `semantic_extraction_report` assets with:

- expected vs observed extraction;
- precision/recall/F1;
- confidence;
- evidence spans;
- regression-ready metadata.

## Local Smoke

`make local-smoke` is the default local proof command. It covers:

- backend imports;
- FastAPI startup and API contract;
- pgvector migration dry-run and ops plan;
- worker/scheduler smoke;
- focused unit tests;
- key Novel OS integration tests;
- Web Admin test/build.

