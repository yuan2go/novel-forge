# Loop Kernel Default Workflow Migration Report

Date: 2026-07-03

## Scope

This pass migrates the main production workflow chain to Loop Kernel as the default executor:

```text
review -> revision task -> revision plan -> editor patch -> draft version -> re-review -> publish gate
```

The change keeps legacy API and workflow operation names compatible while routing the execution proof through `LoopRun`, `LoopStep`, `LoopCheckpoint`, and `LoopReport`.

## Implementation

| Area | Evidence | Behavior |
|---|---|---|
| Loop Kernel main chain outputs | `src/novel_forge/modules/loop_kernel/service.py` | `review_revision_publish` now writes `revision_task`, `revision_plan`, `editor_patch`, `draft_version`, re-review, publish gate, loop run, and loop report. |
| Legacy rework facade | `src/novel_forge/modules/revision/service.py::run_review_rework_loop` | Old callers keep the same return fields, but execution is delegated to `run_loop(loop_type="review_revision_publish")`. |
| Workflow default processor | `src/novel_forge/modules/workflow_nodes/service.py` | `review_rework_loop`, `run_review_rework_loop`, `review_revision_publish`, and `review_revision_publish_loop` are registered service operations routed through Loop Kernel. |
| Failure policy | `workflow_nodes.service::_loop_service_success` | Failed/cancelled LoopRun maps to failed NodeRun, so production workflows fail closed. |
| Runtime policy | `workflow_nodes.service::_operation_requires_context_bundle` | Main-chain loop operations require context bundle evidence under strict runtime policy. |
| Traceability | `LoopRun.content.outputs`, `RevisionTask.content.outputs`, `NodeRun.processor.registry_payload` | Workflow, revision task, and loop assets all reference loop run/report paths. |

## Compatibility

- `/product/revisions/rework-loop` remains unchanged at the API boundary because it calls `run_review_rework_loop`.
- Existing `review_rework_loop` workflow nodes remain valid.
- Existing Agent Center operation `run-review-revision-publish-loop` already used Loop Kernel and remains compatible.
- Provider-backed review/revision still works when `revision_model`, `editor_model`, or `review_model` are passed to the compatibility facade.
- Deterministic workflow execution can run the same chain without requiring provider calls.

## Tests

Passed in this pass:

- `python3 -m compileall -q src/novel_forge/modules/loop_kernel src/novel_forge/modules/revision src/novel_forge/modules/workflow_nodes`
- `python3 -m unittest tests.unit.test_loop_kernel`
- `python3 -m unittest tests.unit.test_workflow_executor`
- `python3 -m unittest tests.unit.test_module_services -k review_rework_loop`
- `python3 -m unittest tests.unit.test_agent_scheduler tests.unit.test_publish_feedback_loop`
- `python3 -m unittest tests.integration.test_novel_os_acceptance`
- `python3 -m unittest tests.unit.test_product_api_routes`

## Remaining Boundaries

| Boundary | Priority | Next Step |
|---|---|---|
| Non-main-chain service operations still run through the workflow processor directly. | P2 | Migrate operation families only when they benefit from step/checkpoint semantics. |
| Provider-backed execution is opt-in through model arguments or future runtime policy, not automatic. | P1 | Add policy-controlled provider execution behind hard-stop and fallback approval. |
| Loop resume currently restarts via workflow resume rather than step-level LoopRun resume. | P2 | Add LoopRun resume from last checkpoint. |
| UI should surface NodeRun -> LoopRun links directly. | P2 | Add workflow detail panel link to LoopRun and LoopReport. |
