# Context Builder Design

Date: 2026-07-03

## Scope

Phase 4 promotes Context Builder from a RAG bundle helper into the unified entry for generation and review context. MKAOS Pack construction now happens inside Context Builder for the P0 flows.

## Unified Entry

New service:

- `src/novel_forge/modules/context_builder/service.py::build_flow_context_bundle`

Supported flow keys:

- `outline`
- `chapter_outline`
- `prose`
- `review`
- `revision`
- `recap`
- `publish`
- `feedback`

P0 flow execution is active for `outline`, `chapter_outline`, `prose`, and `review`. Later flows are pre-adapter paths that map MKAOS rule selection through the review pack until their own services are implemented.

## Context Bundle Shape

The bundle records:

- `context_bundle_id`
- `task_type`
- `target_asset_type`
- `target_asset_id`
- `mkaos_pack`
- `review_rules`
- `prior_issues`
- `revision_constraints`
- `forbidden_changes`
- `token_budget`
- `source_policy`
- `source_isolation`
- `evidence_refs`
- `trace_id`
- `envelope_id`

Compatibility fields such as `mkaos_knowledge_pack`, `mkaos_knowledge_pack_id`, and `mkaos_knowledge_pack_path` are retained.

## Source Isolation

`build_flow_context_bundle` enforces:

- no `source_chunk.raw_text` in MKAOS pack;
- no raw source text in prose / recap / publish context bundles;
- runtime assets remain excluded from generation RAG through existing RAG policy;
- explicit `source_policy` is stored in the bundle.

## Flow Migration

The following services now call `build_flow_context_bundle`:

- `src/novel_forge/modules/outline/service.py`
- `src/novel_forge/modules/chapter_plan/service.py`
- `src/novel_forge/modules/drafting/service.py`
- `src/novel_forge/modules/review/service.py`

These services still keep legacy fields in their artifacts so existing tests, UI, and API consumers do not break.

## Remaining Work

Phase 5 will persist `prior_issues` as ReviewIssue and make blocking gates durable. Phase 6 will use the same context bundle in LoopRun. Phase 7 and Phase 10 will activate recap and publish adapters.
