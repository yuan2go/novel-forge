# Novel OS v6 Remaining Risk Hardening Report

## Scope

This pass hardens the remaining P1/P2 governance risks without replacing existing MKAOS, Context Builder, OS Envelope, Audit Log, Evaluation Center, pgvector, ClickHouse, or Publish Gate modules.

## Implemented

1. Request-level production policy normalization
   - Added `normalize_environment` and `normalize_runtime_request_policy` in `src/novel_forge/modules/os_envelope/service.py`.
   - Publish Gate and Release Package API/service paths now resolve production mode from either top-level `environment` or `os_envelope.environment`.
   - Production policy defaults now set `production_fail_closed=true`, `compat_warning_allowed=false`, `mkaos_pack_required=true`, `source_isolation_required=true`, and `empty_pack_policy=block`.

2. Publish/release fail-closed hardening
   - `create_publish_gate_report` now records EvaluationGate and PlatformStrategyPack/retention-risk governance status.
   - Production Publish Gate blocks when EvaluationGate is missing or blocked.
   - Production Publish Gate blocks when PlatformStrategyPack is missing or platform retention risk is high/critical.
   - `create_release_package` now fails closed in production when the Publish Gate decision is not `ready`.
   - Compat/sample paths can still write blocked release packages for old fixture inspection.

3. Online service proof seams
   - Added `pgvector_online_e2e_smoke`.
   - Added `clickhouse_online_e2e_smoke`.
   - Both default to local/offline warning reports and require explicit online env vars for real service checks.

4. Audit Log expansion
   - Model Gateway now records audit events for successful model calls and provider guard blocks.
   - Tool Gateway now records audit events for tool invocations.
   - Agent rollback and operation transaction rollback preview/apply/coordinate paths now record rollback audit events.

5. Evaluation Center expansion
   - `evaluate_asset` accepts deterministic `human_annotations` and opt-in `model_judge` score payloads.
   - No external model judge is called by default.
   - Evaluation results record `evaluation_mode` and `evaluator_inputs`.

6. Follow-up hardening
   - Added `normalize_product_api_runtime_request` so product routers can share request-level environment/envelope/source-policy normalization.
   - Migrated Editor and Evaluation routes to the shared API runtime helper.
   - Added production enforcement to `apply_editor_patch`: production apply now requires upstream Knowledge Context Contract and a production OS Envelope.
   - Added explicit external model-judge adapter path guarded by `allow_external_model_judge=true`, source isolation, and Model Gateway audit evidence.
   - Added online backend verification surfaces:
     - `POST /product/os/retrieval/pgvector-online-smoke`
     - `POST /product/analytics/online-smoke`
     - `scripts/verify_online_backends.py`
     - `tests/integration/test_online_backends_e2e.py` opt-in real service test.

7. Local online backend execution
   - `docker-compose.yml` now runs `postgres` with `pgvector/pgvector:pg16`, so the local PostgreSQL service supports the `vector` extension.
   - Added optional `clickhouse` under the `analytics` compose profile.
   - Added `make online-backends-up` to start pgvector-capable PostgreSQL and ClickHouse.
   - Added `make online-backends-smoke` to run `scripts/verify_online_backends.py --require-online` with local service environment variables.

8. Full product router policy normalization
   - Added API middleware for every `/product/...` route.
   - Normalized policy is attached to `request.state.runtime_request_policy`, with `request.state.os_envelope` and `request.state.source_policy` aliases.
   - Every product response gets `x-novel-forge-runtime-policy=normalized`.
   - Mutating production product requests without an OS Envelope fail closed at the API boundary.

## Tests Added

- `tests/unit/test_online_service_smoke.py`
- `tests/unit/test_api_policy_normalization.py`
- Added Publish Gate production policy tests in `tests/unit/test_publish_feedback_loop.py`.
- Added Evaluation human/model-judge test in `tests/unit/test_evaluation_center_general.py`.
- Added Audit Log governance event tests in `tests/unit/test_audit_log.py`.
- Added Editor production apply contract tests in `tests/unit/test_agent_editor_continuity_evaluation.py`.

## Verification Commands

```bash
PYTHONPATH=src python3 -m unittest \
  tests.unit.test_publish_feedback_loop \
  tests.unit.test_evaluation_center_general \
  tests.unit.test_audit_log \
  tests.unit.test_online_service_smoke \
  tests.unit.test_api_policy_normalization \
  tests.unit.test_agent_editor_continuity_evaluation
```

Real backend opt-in:

```bash
make online-backends-up
make online-backends-smoke

NOVEL_FORGE_PGVECTOR_ONLINE=1 NOVEL_FORGE_CLICKHOUSE_ONLINE=1 \
PYTHONPATH=src python3 -m unittest tests.integration.test_online_backends_e2e

NOVEL_FORGE_PGVECTOR_ONLINE=1 NOVEL_FORGE_CLICKHOUSE_ONLINE=1 \
PYTHONPATH=src python3 scripts/verify_online_backends.py --require-online
```

Additional targeted commands should include existing MKAOS/context/publish suites before merge:

```bash
PYTHONPATH=src python3 -m unittest tests.unit.test_mkaos tests.unit.test_mkaos_fail_closed_policy tests.unit.test_mkaos_agent_context_contract
PYTHONPATH=src python3 -m unittest tests.integration.test_novel_os_long_chain_smoke
```

## Remaining Risks

- Real PostgreSQL + pgvector and ClickHouse online E2E now have scripts/tests/endpoints and a local Docker stack. CI or remote production service validation still requires operator-managed credentials and health checks.
- Evaluation external judge is implemented behind explicit opt-in and Model Gateway evidence; non-mock providers still require provider secrets and runtime guard configuration.
- Request-level API policy normalization covers all product routers. Service-level fail-closed propagation remains explicit in the critical publishing/editor/evaluation paths and can be deepened per lower-risk router when those operations gain production semantics.
