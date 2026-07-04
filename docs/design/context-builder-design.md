# Context Builder Design

Date: 2026-07-03

## Scope

Phase 4 promotes Context Builder from a RAG bundle helper into the unified entry for generation and review context. MKAOS Pack construction now happens inside Context Builder for the core Novel OS Agent flows.

## Unified Entry

New service:

- `src/novel_forge/modules/context_builder/service.py::build_flow_context_bundle`

Supported flow keys:

- `analysis`
- `decompose`
- `convert`
- `outline`
- `chapter_plan`
- `chapter_outline`
- `draft`
- `prose`
- `review`
- `revision`
- `editor_patch`
- `recap`
- `publish`
- `publish_gate`
- `feedback`
- `feedback_backflow`

User-facing operation flows are normalized to standard MKAOS flows before pack construction:

| Operation Flow | MKAOS Flow |
| -- | -- |
| `analysis` / `decompose` / `convert` | `review` |
| `outline` | `outline` |
| `chapter_plan` / `chapter_outline` | `chapter_outline` |
| `draft` / `prose` | `prose` |
| `review` | `review` |
| `revision` / `editor_patch` | `revision` |
| `recap` | `recap` |
| `publish` / `publish_gate` | `publish` |
| `feedback` / `feedback_backflow` | `feedback` |

## Context Bundle Shape

The bundle records:

- `context_bundle_id`
- `task_type`
- `target_asset_type`
- `target_asset_id`
- `mkaos_pack`
- `mkaos_flow`
- `knowledge_context_contract`
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
- no raw source text in prose / review / recap / publish context bundles and their operation aliases such as `draft` and `publish_gate`;
- runtime assets remain excluded from generation RAG through existing RAG policy;
- explicit `source_policy` is stored in the bundle.

## Flow Migration

The following services now call `build_flow_context_bundle` or the Context Builder-backed MKAOS helper:

- `src/novel_forge/modules/analysis/service.py`
- `src/novel_forge/modules/decomposition/service.py`
- `src/novel_forge/modules/outline/service.py`
- `src/novel_forge/modules/chapter_plan/service.py`
- `src/novel_forge/modules/drafting/service.py`
- `src/novel_forge/modules/review/service.py`
- `src/novel_forge/modules/revision/service.py`
- `src/novel_forge/modules/editor/service.py`
- `src/novel_forge/modules/longform_recap/service.py`
- `src/novel_forge/modules/audit/service.py`
- `src/novel_forge/modules/feedback_backflow/service.py`
- `src/novel_forge/modules/feedback/service.py`

These services still keep legacy fields in their artifacts so existing tests, UI, and API consumers do not break.

## Remaining Work

`apply-editor-patch` remains a compatibility operation because it consumes an upstream editor patch that should already contain the contract. New production editor patch creation must use `create-editor-patch`, which is MKAOS-required. UI surfacing can still be expanded to make the contract visible on every AgentRun detail panel.
