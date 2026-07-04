# MKAOS Agent Knowledge Context Contract Report

Date: 2026-07-04

## Scope

This change upgrades MKAOS from an optional knowledge service to the mandatory knowledge context entry for core Novel OS Agent operations.

Covered operations:

| Operation | Status | Entry Point | Evidence |
| -- | -- | -- | -- |
| analysis | required | Context Builder | `src/novel_forge/modules/analysis/service.py` |
| decompose | required | Context Builder | `src/novel_forge/modules/decomposition/service.py` |
| convert | required | Context Builder | `src/novel_forge/modules/analysis/service.py` |
| outline | required | Context Builder-backed MKAOS helper | `src/novel_forge/modules/outline/service.py` |
| chapter_plan | required | Context Builder-backed MKAOS helper | `src/novel_forge/modules/chapter_plan/service.py` |
| draft | required | Context Builder-backed MKAOS helper | `src/novel_forge/modules/drafting/service.py` |
| review | required | Context Builder-backed MKAOS helper | `src/novel_forge/modules/review/service.py` |
| revision | required | Context Builder | `src/novel_forge/modules/revision/service.py` |
| editor_patch | required | Context Builder | `src/novel_forge/modules/editor/service.py` |
| recap | required | Context Builder | `src/novel_forge/modules/longform_recap/service.py` |
| publish_gate | required | Context Builder | `src/novel_forge/modules/audit/service.py` |
| feedback_backflow | required | Context Builder | `src/novel_forge/modules/feedback/service.py`, `src/novel_forge/modules/feedback_backflow/service.py` |

Operation names are normalized before MKAOS pack construction, so scheduler-facing names and service-facing flow names cannot drift:

| Operation Flow | Standard MKAOS Flow |
| -- | -- |
| `analysis`, `decompose`, `convert` | `review` |
| `outline` | `outline` |
| `chapter_plan`, `chapter_outline` | `chapter_outline` |
| `draft`, `prose` | `prose` |
| `review` | `review` |
| `revision`, `editor_patch` | `revision` |
| `recap` | `recap` |
| `publish`, `publish_gate` | `publish` |
| `feedback`, `feedback_backflow` | `feedback` |

## Knowledge Context Contract

The unified contract is generated in `build_flow_context_bundle` and stored on both context bundles and downstream Agent outputs.

Required fields:

- `context_bundle_id`
- `knowledge_pack_id`
- `source_policy`
- `source_isolation`
- `mkaos_flow`
- `selected_knowledge_ids`
- `review_rules`
- `risk_warnings`
- `selector_policy_version`

The contract version is `knowledge-context-contract-v1`.

## Enforcement

- `ContextBuilder` always adds an MKAOS `knowledge_pack` and contract to flow context bundles.
- `AgentExecutionContext` writes `context_bundle_id`, `knowledge_pack_id`, `mkaos_flow`, selected knowledge ids, and the full contract into AgentRun metadata.
- `AgentOperationRegistry` exposes both canonical operation coverage and user-facing operation alias coverage, and forbids production bypass for required operations.
- Production `output_reuse` and `local_service` execution paths fail closed if a required operation lacks the contract.
- `apply-editor-patch` remains `compat` because it can consume an already-built context bundle from the revision execution path.
- Direct real feedback backflow service calls now validate the contract in production, matching the Agent Scheduler enforcement path.
- MKAOS pack output contracts now cover `revision`, `recap`, `publish`, and `feedback`, so those flows build real packs instead of falling back to `review`.

## Source Isolation

The contract records source policy and source isolation explicitly. `source_chunk.raw_text` remains disallowed for generation, prose, publish, recap, and prompt-preview paths. Recap leakage tests were refined to reject raw-text payloads while allowing false-valued policy keys such as `source_chunk_raw_text_allowed=false`.

## Storage Performance Note

The wider contract propagation increased reference counts on run and context assets. Pipeline replay exposed a pre-existing `LocalStorage` project-scope guard hotspot that scanned every data directory per reference. `LocalStorage._project_id_for_reference` now uses candidate directories derived from asset id/path shape, matching the existing `production_context` approach.

## Test Results

| Command | Result |
| -- | -- |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_mkaos_agent_context_contract tests.unit.test_agent_operation_mkaos_coverage` | 6 tests OK |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_context_builder_mkaos_flow tests.unit.test_mkaos_fail_closed_policy tests.unit.test_publish_feedback_loop tests.unit.test_longform_recap_agent tests.unit.test_agent_scheduler tests.unit.test_mkaos` | 33 tests OK, 1 existing Starlette/httpx deprecation warning |
| `PYTHONPATH=src python3 -m unittest tests.integration.test_novel_os_long_chain_smoke` | 1 test OK |
| `PYTHONPATH=src python3 -m compileall -q src/novel_forge/modules/context_builder src/novel_forge/modules/agent_scheduler src/novel_forge/modules/mkaos src/novel_forge/modules/feedback tests/unit/test_mkaos_agent_context_contract.py tests/unit/test_agent_operation_mkaos_coverage.py tests/unit/test_longform_recap_agent.py` | OK |

## Remaining Risk

- The old sample pipeline still takes several minutes because it performs broad local asset validation and second-run idempotency checks.
- `apply-editor-patch` is intentionally compat until every historical editor invocation is guaranteed to receive an upstream context bundle.
- Frontend-specific visibility for the contract was not expanded in this change; AgentRun metadata now contains the data needed for UI surfacing.
