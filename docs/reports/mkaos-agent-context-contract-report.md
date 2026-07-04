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
| feedback_backflow | required | Context Builder | `src/novel_forge/modules/feedback.py`, `src/novel_forge/modules/feedback_backflow/service.py` |

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
- `AgentOperationRegistry` exposes operation-level MKAOS coverage and forbids production bypass for required operations.
- Production `output_reuse` and `local_service` execution paths fail closed if a required operation lacks the contract.
- `apply-editor-patch` remains `compat` because it can consume an already-built context bundle from the revision execution path.

## Source Isolation

The contract records source policy and source isolation explicitly. `source_chunk.raw_text` remains disallowed for generation, prose, publish, recap, and prompt-preview paths. Recap leakage tests were refined to reject raw-text payloads while allowing false-valued policy keys such as `source_chunk_raw_text_allowed=false`.

## Storage Performance Note

The wider contract propagation increased reference counts on run and context assets. Pipeline replay exposed a pre-existing `LocalStorage` project-scope guard hotspot that scanned every data directory per reference. `LocalStorage._project_id_for_reference` now uses candidate directories derived from asset id/path shape, matching the existing `production_context` approach.

## Test Results

| Command | Result |
| -- | -- |
| `python3 -m compileall -q src/novel_forge/storage src/novel_forge/modules/context_builder src/novel_forge/modules/agent_runs src/novel_forge/modules/agent_scheduler` | OK |
| `python3 -m unittest tests.unit.test_agent_operation_mkaos_coverage tests.unit.test_mkaos_agent_context_contract tests.unit.test_context_builder_mkaos_flow tests.unit.test_mkaos_fail_closed_policy tests.unit.test_publish_feedback_loop tests.unit.test_longform_recap_agent tests.unit.test_agent_scheduler tests.unit.test_mkaos` | 37 tests OK, 1 existing Starlette/httpx deprecation warning |
| `python3 -m unittest tests.integration.test_pipeline` | 1 test OK, 386.830s |

## Remaining Risk

- The old sample pipeline still takes several minutes because it performs broad local asset validation and second-run idempotency checks.
- `apply-editor-patch` is intentionally compat until every historical editor invocation is guaranteed to receive an upstream context bundle.
- Frontend-specific visibility for the contract was not expanded in this change; AgentRun metadata now contains the data needed for UI surfacing.
