# MKAOS Pack Fail-Closed Policy Report

Date: 2026-07-04

## Scope

This change hardens MKAOS pack construction across the main Novel OS production chain. The goal is to keep compatibility mode usable while preventing production, strict, and operating-system paths from silently continuing without a governed `ContextBundle` and `KnowledgePack`.

Covered paths:

- `build_flow_context_bundle`
- Outline generation
- Chapter plan generation
- Draft/prose generation
- Review
- Publish gate
- Longform recap
- Loop Kernel context resolution
- Agent Scheduler context-bundle operation

## Policy

The shared policy is implemented in `src/novel_forge/modules/mkaos/pack_policy.py`.

| Field | Meaning | Production / strict | Dev / sample / compat |
|---|---|---|---|
| `mkaos_pack_required` | A governed pack must exist. | `true` | `false` by default |
| `context_bundle_required` | A context bundle must exist for the pack consumer. | `true` | `false` by default |
| `knowledge_pack_id_required` | The pack asset must carry `knowledge_pack_id`. | `true` | `false` by default |
| `compat_warning_allowed` | Pack failure may degrade to warning. | `false` | `true` |
| `empty_pack_policy` | Behavior when `pack_items` is empty. | `block` for `prose`, `review`, `publish`, `recap`; otherwise `warn` | `warn` |
| `source_isolation_required` | Raw source text must not enter generated context. | `true` | `true` |

Strict mode is resolved through `is_production_environment`, so the same behavior applies to production-like runtime policy environments.

## Implementation

The repeated `_build_mkaos_pack` fallback logic in Outline, ChapterPlan, Drafting, and Review now delegates to `build_mkaos_flow_context_with_policy`. That helper:

1. Resolves the runtime policy from `flow` and `environment`.
2. Runs the provided Context Builder/MKAOS builder.
3. Fails closed in production/strict paths.
4. Allows warning fallback only in compat paths.
5. Records a `trace_span` and `runtime_policy` gate result for warning/failure events.
6. Validates missing pack, missing context bundle, missing `knowledge_pack_id`, empty pack, and raw source leakage.
7. Writes policy metadata back to the pack or fallback packet.

`build_flow_context_bundle` now applies the same validation after MKAOS pack construction and records `mkaos_pack_policy`, `mkaos_runtime_policy_warning_path`, and `mkaos_pack_trace_span_path` in both content and metadata.

## Fail-Closed Behavior

Production/strict paths now block when:

- `build_knowledge_pack` raises;
- the context bundle is missing;
- `knowledge_pack_id` is missing;
- `source_chunk.raw_text` or any `raw_text` key reaches MKAOS pack content;
- `prose`, `review`, `publish`, or `recap` receives an empty pack.

Compat paths may continue with a warning fallback, but the fallback is no longer silent. It carries:

- `mkaos_pack_policy`;
- warning text;
- runtime policy gate path;
- trace span path;
- source isolation proof metadata.

## Tests

Added `tests/unit/test_mkaos_fail_closed_policy.py`:

- mock `build_knowledge_pack` exception blocks production;
- `strict` and `operating_system` aliases block pack failures;
- mock `build_knowledge_pack` exception records compat warning;
- production prose empty pack blocks;
- production missing `knowledge_pack_id` blocks;
- production missing context bundle blocks at policy validation;
- source isolation failure blocks even in compat.

Related regression tests were also run for Context Builder, MKAOS isolation, OS Envelope, publish/feedback, Loop Kernel, longform recap, and production-chain behavior.

## Verification

Commands run:

```bash
python3 -m unittest tests.unit.test_mkaos_fail_closed_policy
python3 -m unittest tests.unit.test_context_builder_mkaos_flow tests.unit.test_mkaos_isolation tests.unit.test_mkaos_os_envelope
python3 -m unittest tests.unit.test_publish_feedback_loop tests.unit.test_loop_kernel tests.unit.test_longform_recap_agent tests.unit.test_context_and_production_chain tests.unit.test_mkaos_fail_closed_policy
```

Results:

- `tests.unit.test_mkaos_fail_closed_policy`: 7 tests OK
- Context Builder / MKAOS isolation / OS Envelope group: 13 tests OK
- Publish / Loop / Longform / production-chain group: 32 tests OK

## Remaining Risk

- Some legacy call sites still expose optional `environment`/`os_envelope` parameters rather than a request-level runtime object. The policy now blocks production failures when those fields are supplied, but API-level production request normalization should continue to be tightened.
- Compat fallback remains intentionally allowed for old fixtures and sample pipelines; future acceptance tests should assert that canonical chapter and release package operations always pass explicit production policy when running in operating-system mode.
